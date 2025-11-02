# app/api/routes/webhook.py

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.core.config import settings
from app.services.messenger import send_ig_message
from app.services.token_store import get_token_store

logger = logging.getLogger(__name__)

# Dos routers:
# - router:     se monta con prefix="/webhook"  -> /webhook/instagram
# - router_public: sin prefix                   -> /webhooks/instagram
router = APIRouter()
router_public = APIRouter()

# --------------------------------------------------------------------------------------
# Helpers de firma/verificación
# --------------------------------------------------------------------------------------

def _clean_sig(sig: str) -> str:
    """Acepta 'sha1=abcd' / 'sha256=abcd' o solo 'abcd'."""
    return (sig or "").split("=", 1)[-1].strip()


def _valid_signature(sig_sha1: Optional[str], sig_sha256: Optional[str], body: bytes) -> bool:
    """
    Valida HMAC con APP_SECRET. Prefiere SHA-256 y cae a SHA-1 si aplica.
    Usa los BYTES CRUDOS del cuerpo (tal cual los envía Meta).
    """
    secret = (getattr(settings, "APP_SECRET", "") or "").strip().encode()
    if not secret:
        return False

    try:
        if sig_sha256:
            expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
            provided = _clean_sig(sig_sha256)
        elif sig_sha1:
            expected = hmac.new(secret, body, hashlib.sha1).hexdigest()
            provided = _clean_sig(sig_sha1)
        else:
            return False
        return hmac.compare_digest(expected, provided)
    except Exception:
        return False


def _verify_instagram_webhook_impl(request: Request) -> Response:
    """Responder el reto (hub.challenge) de verificación."""
    qp = request.query_params
    hub_mode = qp.get("hub.mode") or qp.get("hub_mode")
    hub_challenge = qp.get("hub.challenge") or qp.get("hub_challenge")
    hub_verify_token = qp.get("hub.verify_token") or qp.get("hub_verify_token")

    if hub_mode == "subscribe" and hub_verify_token == getattr(settings, "VERIFY_TOKEN", None):
        return Response(content=str(hub_challenge or ""), media_type="text/plain")

    raise HTTPException(status_code=403, detail="Token de verificación inválido")

# --------------------------------------------------------------------------------------
# Push al Core unificado
# --------------------------------------------------------------------------------------

def _iso_utc_from_ms(ts_ms: Optional[int]) -> str:
    if ts_ms:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
    return datetime.now(tz=timezone.utc).isoformat()

async def _push_to_core_unified(
    *,
    sender_psid: str,
    page_id: Optional[str],
    mid: Optional[str],
    text: str,
    ts_ms: Optional[int],
):
    """
    Envía el mensaje al Core /api/v1/messages/unified con body PLANO.
    Esquema esperado por el Core:
      - channel: "instagram"
      - conversation_id: str
      - external_message_id: str
      - sender_identifier: str
      - recipient_identifier: str
      - message: str
      - message_type: "text"
      - direction: "incoming" | "outgoing"
      - timestamp: ISO8601 (UTC)
      - metadata: dict (opcional)
    """
    if not getattr(settings, "CORE_UNIFIED_URL", None):
        logger.warning("CORE_UNIFIED_URL no configurado; no se envía al Core.")
        return

    # ID de conversación “estable”
    conversation_id = f"{sender_psid}:{page_id or ''}".strip(":")

    # Timestamp ISO8601 en UTC
    ts_iso = _iso_utc_from_ms(ts_ms)

    # Metadata opcional con info de tokens
    token_store = get_token_store()
    tokens = await token_store.get_tokens()
    metadata: Dict[str, Any] = {
        "page_id": getattr(tokens, "page_id", None) or page_id,
        "ig_user_id": getattr(tokens, "ig_user_id", None),
    }

    # Body PLANO que el Core valida correctamente
    body = {
        "channel": "instagram",
        "sender": sender_psid,
        "message": text or "",
        "timestamp": ts_iso,
        "message_type":"text",
    }

    headers = {"Content-Type": "application/json"}
    if getattr(settings, "CORE_API_KEY", None):
        headers["X-API-Key"] = settings.CORE_API_KEY  # opcional si su Core lo requiere

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(settings.CORE_UNIFIED_URL, json=body, headers=headers)
        logger.info("➡️  Push Core %s %s", r.status_code, r.text)
        r.raise_for_status()

# --------------------------------------------------------------------------------------
# GET (verify)
# --------------------------------------------------------------------------------------

@router.get("/instagram")
async def verify_instagram_webhook_prefixed(request: Request):
    return _verify_instagram_webhook_impl(request)

@router_public.get("/webhooks/instagram")
async def verify_instagram_webhook_root(request: Request):
    return _verify_instagram_webhook_impl(request)

# --------------------------------------------------------------------------------------
# POST (events)
# --------------------------------------------------------------------------------------

async def _receive_instagram_webhook_impl(
    request: Request,
    x_hub_signature: Optional[str],
    x_hub_signature_256: Optional[str],
):
    # Bytes crudos (para firma)
    body = await request.body()

    # Firmas
    sig_sha1 = x_hub_signature or request.headers.get("X-Hub-Signature")
    sig_sha256 = x_hub_signature_256 or request.headers.get("X-Hub-Signature-256")
    logger.info("🪪 Firmas: X-Hub-Signature=%s | X-Hub-Signature-256=%s", sig_sha1, sig_sha256)

    # Validación de firma (solo estricta en producción)
    if getattr(settings, "APP_SECRET", None) and not _valid_signature(sig_sha1, sig_sha256, body):
        if (getattr(settings, "ENV", "development") or "development").lower() != "production":
            logger.warning("⚠️ Firma inválida, bypass por entorno=%s", getattr(settings, "ENV", None))
        else:
            raise HTTPException(status_code=401, detail="Firma inválida")

    # Payload
    payload = await request.json()
    logger.info("📩 Payload:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))

    # Recorrido de eventos (estilo Messenger/IG)
    # Meta puede enviar tanto entry[].changes[].value.messaging[] como entry[].messaging[]
    entries = payload.get("entry", [])
    for entry in entries:
        # Variante A: messaging directo
        events = entry.get("messaging")
        if not events:
            # Variante B: dentro de changes[].value.messaging
            events = []
            for change in entry.get("changes", []):
                value = change.get("value", {})
                events.extend(value.get("messaging", []))

        for event in events or []:
            sender = (event.get("sender") or {}).get("id")
            recipient = (event.get("recipient") or {}).get("id")
            ts_ms = event.get("timestamp")

            if "message" in event:
                text = (event["message"] or {}).get("text") or ""
                mid = (event["message"] or {}).get("mid")

                hora = datetime.fromtimestamp((ts_ms or 0) / 1000).strftime("%H:%M:%S") if ts_ms else "?"
                logger.info("💬 %s | PSID:%s → Page:%s | mid:%s | “%s”", hora, sender, recipient, mid, text)

                # 1) Enviar al Core (unified)
                try:
                    await _push_to_core_unified(
                        sender_psid=sender or "",
                        page_id=recipient or "",
                        mid=mid or "",
                        text=text or "",
                        ts_ms=ts_ms,
                    )
                except Exception as e:
                    logger.exception("❌ Error al enviar al Core: %s", e)

                # 2) (Opcional) Responder eco al usuario en IG
                try:
                    if getattr(settings, "PAGE_ACCESS_TOKEN", None):
                        resp = await send_ig_message(sender, f"Recibí: {text or '(sin texto)'}")
                        logger.info("✅ Respuesta enviada | %s", resp)
                    else:
                        logger.info("ℹ️ PAGE_ACCESS_TOKEN no configurado; no se envía eco.")
                except Exception as e:
                    logger.exception("❌ Error enviando respuesta: %s", e)

            elif "read" in event:
                watermark = (event["read"] or {}).get("watermark")
                logger.info("👁️  PSID:%s leyó hasta %s", sender, watermark)
            elif "delivery" in event:
                mids = (event["delivery"] or {}).get("mids")
                logger.info("📬 Entregado: %s", mids)
            else:
                logger.info("ℹ️  Evento no manejado: %s", list(event.keys()))

    return {"received": True}

@router.post("/instagram")
async def receive_instagram_webhook_prefixed(
    request: Request,
    x_hub_signature: Optional[str] = Header(default=None, convert_underscores=False),
    x_hub_signature_256: Optional[str] = Header(default=None, convert_underscores=False),
):
    return await _receive_instagram_webhook_impl(request, x_hub_signature, x_hub_signature_256)

@router_public.post("/webhooks/instagram")
async def receive_instagram_webhook_root(
    request: Request,
    x_hub_signature: Optional[str] = Header(default=None, convert_underscores=False),
    x_hub_signature_256: Optional[str] = Header(default=None, convert_underscores=False),
):
    return await _receive_instagram_webhook_impl(request, x_hub_signature, x_hub_signature_256)

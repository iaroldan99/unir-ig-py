import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.core.config import settings
from app.services.messenger import send_ig_message

logger = logging.getLogger(__name__)

router = APIRouter()
router_public = APIRouter()


# ------------------------- helpers -------------------------

def _clean_sig(sig: str) -> str:
    """Acepta 'sha1=abcd' / 'sha256=abcd' o solo 'abcd'."""
    return (sig or "").split("=", 1)[-1].strip()


def _valid_signature(sig_sha1: Optional[str], sig_sha256: Optional[str], body: bytes) -> bool:
    """
    Valida HMAC con APP_SECRET. Prefiere SHA-256 y cae a SHA-1 si aplica.
    Usa los BYTES CRUDOS del cuerpo (tal cual los envía Meta).
    """
    secret = (settings.APP_SECRET or "").strip().encode()
    if not secret:
        return False

    try:
        if sig_sha256:
            expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, _clean_sig(sig_sha256))
        if sig_sha1:
            expected = hmac.new(secret, body, hashlib.sha1).hexdigest()
            return hmac.compare_digest(expected, _clean_sig(sig_sha1))
    except Exception:
        pass
    return False


def _verify_instagram_webhook_impl(request: Request) -> Response:
    """Responder el reto (hub.challenge) de verificación."""
    qp = request.query_params
    hub_mode = qp.get("hub.mode") or qp.get("hub_mode")
    hub_challenge = qp.get("hub.challenge") or qp.get("hub_challenge")
    hub_verify_token = qp.get("hub.verify_token") or qp.get("hub_verify_token")

    if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
        return Response(content=str(hub_challenge or ""), media_type="text/plain")

    raise HTTPException(status_code=403, detail="Token de verificación inválido")


# ------------------------- GET (verify) -------------------------

@router.get("/instagram")
async def verify_instagram_webhook_prefixed(request: Request):
    return _verify_instagram_webhook_impl(request)


@router_public.get("/webhooks/instagram")
async def verify_instagram_webhook_root(request: Request):
    return _verify_instagram_webhook_impl(request)


# ------------------------- POST (events) -------------------------

async def _receive_instagram_webhook_impl(
    request: Request,
    x_hub_signature: Optional[str],
    x_hub_signature_256: Optional[str],
):
    # Leer bytes CRUDOS UNA sola vez
    body = await request.body()

    # Log de headers de firma
    sig_sha1 = x_hub_signature or request.headers.get("X-Hub-Signature")
    sig_sha256 = x_hub_signature_256 or request.headers.get("X-Hub-Signature-256")
    logger.info("🪪 Firmas: X-Hub-Signature=%s | X-Hub-Signature-256=%s", sig_sha1, sig_sha256)

    # Validación de firma (bypass en entornos no productivos para diagnóstico)
    if settings.APP_SECRET and not _valid_signature(sig_sha1, sig_sha256, body):
        if (settings.ENV or "development").lower() != "production":
            logger.warning("⚠️ Firma inválida, bypass por entorno=%s", settings.ENV)
        else:
            raise HTTPException(status_code=401, detail="Firma inválida")

    # Parseo seguro del payload y pretty log
    payload = await request.json()
    logger.info("📩 Payload:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))

    # Enrutado de eventos: entry[] -> changes[] -> value.messaging[]
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            events = value.get("messaging", [])
            for event in events:
                sender = event.get("sender", {}).get("id")
                recipient = event.get("recipient", {}).get("id")
                ts_ms = event.get("timestamp")
                hora = datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S") if ts_ms else "?"

                # Mensaje entrante
                if "message" in event:
                    text = event["message"].get("text") or ""
                    mid = event["message"].get("mid")
                    logger.info("💬 %s | PSID:%s → Page:%s | mid:%s | “%s”",
                                hora, sender, recipient, mid, text)

                    # ✅ PUSH AL CORE (nuevo bloque)
                    try:
                        import httpx
                        from app.services.token_store import get_token_store

                        if settings.CORE_UNIFIED_URL and sender and mid:
                            token_store = get_token_store()
                            tokens = await token_store.get_tokens()
                            unified = {
                                "channel": "instagram",
                                "external_conversation_id": sender,
                                "external_message_id": mid,
                                "sender": sender,
                                "recipient": tokens.ig_user_id if tokens else recipient,
                                "direction": "incoming",
                                "message_type": "text",
                                "content": text or "",
                                "timestamp": datetime.utcfromtimestamp(
                                    (ts_ms or 0)/1000.0
                                ).isoformat() + "Z",
                                "metadata": {
                                    "page_id": tokens.page_id if tokens else recipient,
                                    "ig_user_id": tokens.ig_user_id if tokens else None
                                }
                            }
                            headers = {"Content-Type": "application/json"}
                            if settings.CORE_API_KEY:
                                headers["X-API-Key"] = settings.CORE_API_KEY

                            async with httpx.AsyncClient(timeout=10) as client:
                                r = await client.post(
                                    settings.CORE_UNIFIED_URL,
                                    json=unified,
                                    headers=headers
                                )
                                r.raise_for_status()
                            logger.info("➡️ Enviado a Core unified: %s", r.text)
                    except Exception as e:
                        logger.exception("❌ Error al enviar al Core: %s", e)

                    # Respuesta de eco (opcional)
                    try:
                        resp = await send_ig_message(sender, f"Recibí: {text or '(sin texto)'}")
                        logger.info("✅ Respuesta enviada | %s", resp)
                    except Exception as e:
                        logger.exception("❌ Error enviando respuesta: %s", e)

                # Lecturas / entregas / otros eventos
                elif "read" in event:
                    watermark = event["read"].get("watermark")
                    logger.info("👁️  %s | PSID:%s leyó hasta %s", hora, sender, watermark)
                elif "delivery" in event:
                    mids = event["delivery"].get("mids")
                    logger.info("📬 %s | Entregado: %s", hora, mids)
                else:
                    logger.info("ℹ️  %s | Evento no manejado: %s", hora, list(event.keys()))

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

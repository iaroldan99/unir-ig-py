import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
import httpx
import hmac
from hashlib import sha256

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

    # Enrutado de eventos:
    # - Variante A (IG/Messenger clásica): entry[].messaging[]
    # - Variante B (cambios): entry[].changes[].value.messaging[]
    for entry in payload.get("entry", []):
        events_list = []
        if "messaging" in entry:
            events_list = entry.get("messaging", [])
        else:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                events_list.extend(value.get("messaging", []))

        for event in events_list:
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

                    # Respuesta de eco (puedes desactivar o mejorar la lógica)
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

                # Reenvío a Core si está configurado
                if settings.CORE_API_URL:
                    try:
                        msg_obj = (event.get("message") or {})
                        text = msg_obj.get("text") or ""
                        mid = msg_obj.get("mid") or ""
                        # timestamp como string ISO8601 (UTC)
                        ts_iso = (
                            datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%dT%H:%M:%SZ")
                            if ts_ms else ""
                        )
                        unified_event = {
                            "channel": "instagram",
                            "sender": sender or "",
                            "message": text,
                            "timestamp": ts_iso,
                            "message_id": mid,
                            "message_type": "text",
                            "sender_name": "",  # desconocido en webhook; completar si se dispone
                        }
                        url = settings.CORE_API_URL.rstrip("/") + "/api/v1/messages/unified"
                        headers = {}
                        if settings.CORE_SECRET_KEY:
                            msg_bytes = json.dumps(unified_event, ensure_ascii=False).encode("utf-8")
                            signature = hmac.new(settings.CORE_SECRET_KEY.encode("utf-8"), msg_bytes, sha256).hexdigest()
                            headers["X-Core-Signature"] = f"sha256={signature}"
                        async with httpx.AsyncClient(timeout=10) as client:
                            r = await client.post(url, json=unified_event, headers=headers)
                            if r.status_code >= 300:
                                logger.warning("↪️ Core respondió %s: %s", r.status_code, r.text)
                            else:
                                logger.info("↪️ Evento reenviado a Core OK")
                    except Exception as e:
                        logger.exception("❌ Error reenviando a Core: %s", e)

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

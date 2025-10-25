# app/api/routes/webhook.py

import hashlib
import hmac
import logging
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
    """Valida HMAC con APP_SECRET para SHA-256 (preferido) y SHA-1."""
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
    logger.info("Headers: X-Hub-Signature=%s  X-Hub-Signature-256=%s", sig_sha1, sig_sha256)

    # Validación de firma (quitar el bypass en prod)
    if settings.APP_SECRET and not _valid_signature(sig_sha1, sig_sha256, body):
        raise HTTPException(status_code=401, detail="Firma inválida")

    # Parseo seguro del payload
    payload = await request.json()
    logger.info("Webhook recibido: %s", payload)

    # Enrutado de eventos: entry[] -> changes[] -> value.messaging[]
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for event in value.get("messaging", []):
                psid = event.get("sender", {}).get("id")
                if not psid:
                    continue

                if "message" in event:
                    text = event["message"].get("text") or ""
                    try:
                        await send_ig_message(psid, f"Recibí: {text or '(sin texto)'}")
                    except Exception as e:
                        logger.exception("Error enviando respuesta: %s", e)

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

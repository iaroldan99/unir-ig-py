# app/api/webhooks_controller.py  (tu archivo actual)

import hmac
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from app.core.config import settings
from app.services.messenger import send_ig_message  # <-- nuevo import

logger = logging.getLogger(__name__)
router = APIRouter()
router_public = APIRouter()

def _verify_instagram_webhook_impl(request: Request) -> Response:
    qp = request.query_params
    hub_mode = qp.get("hub.mode") or qp.get("hub_mode")
    hub_challenge = qp.get("hub.challenge") or qp.get("hub_challenge")
    hub_verify_token = qp.get("hub.verify_token") or qp.get("hub_verify_token")

    if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
        return Response(content=str(hub_challenge or ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

@router.get("/instagram")
async def verify_instagram_webhook_prefixed(request: Request):
    return _verify_instagram_webhook_impl(request)

@router_public.get("/webhooks/instagram")
async def verify_instagram_webhook_root(request: Request):
    return _verify_instagram_webhook_impl(request)

def _valid_signature(signature_sha1: Optional[str], signature_sha256: Optional[str], body: bytes) -> bool:
    """
    Meta puede enviar X-Hub-Signature (sha1) o X-Hub-Signature-256 (sha256).
    Validamos cualquiera de los dos.
    """
    # sha256 (preferido en Instagram Graph / versiones nuevas)
    if signature_sha256:
        try:
            algo, signature = signature_sha256.split("=", 1)
            if algo == "sha256":
                digest = hmac.new(settings.APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
                if hmac.compare_digest(digest, signature):
                    return True
        except Exception:
            pass

    # sha1 (usado históricamente por Messenger)
    if signature_sha1:
        try:
            algo, signature = signature_sha1.split("=", 1)
            if algo == "sha1":
                digest = hmac.new(settings.APP_SECRET.encode(), body, hashlib.sha1).hexdigest()
                if hmac.compare_digest(digest, signature):
                    return True
        except Exception:
            pass

    return False

async def _receive_instagram_webhook_impl(
    request: Request,
    x_hub_signature: Optional[str],
    x_hub_signature_256: Optional[str],
):
    body = await request.body()
    if settings.APP_SECRET and not _valid_signature(x_hub_signature, x_hub_signature_256, body):
        raise HTTPException(status_code=401, detail="Firma inválida")

    payload = await request.json()
    logger.info("Webhook recibido: %s", payload)

    # ---- enrutar eventos tipo "messaging" (Messenger API for Instagram) ----
    # Estructura típica: entry[] -> changes[] -> value{ messaging: [...] }
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for event in value.get("messaging", []):
                psid = event.get("sender", {}).get("id")
                if not psid:
                    continue

                # Mensaje entrante de texto
                if "message" in event:
                    text = event["message"].get("text", "") or ""
                    # Respuesta de eco:
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

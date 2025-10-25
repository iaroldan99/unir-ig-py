import hmac
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.core.config import settings


logger = logging.getLogger(__name__)
router = APIRouter()
router_public = APIRouter()


def _verify_instagram_webhook_impl(request: Request) -> Response:
    # Acepta tanto query params con alias 'hub.*' como implementaciones de proxies
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


def _valid_signature(signature_header: Optional[str], body: bytes) -> bool:
    if not signature_header:
        return False
    try:
        algo, signature = signature_header.split("=", 1)
        if algo != "sha1":
            return False
        digest = hmac.new(settings.APP_SECRET.encode(), body, hashlib.sha1).hexdigest()
        return hmac.compare_digest(digest, signature)
    except Exception:  # pragma: no cover - robustez
        return False


async def _receive_instagram_webhook_impl(request: Request, x_hub_signature: Optional[str]):
    body = await request.body()
    if settings.APP_SECRET and not _valid_signature(x_hub_signature, body):
        raise HTTPException(status_code=401, detail="Firma inválida")

    payload = await request.json()
    logger.info("Webhook recibido: %s", payload)
    # TODO: enrutar eventos a handlers, almacenar, emitir a websockets, etc.
    return {"received": True}


@router.post("/instagram")
async def receive_instagram_webhook_prefixed(
    request: Request,
    x_hub_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    return await _receive_instagram_webhook_impl(request, x_hub_signature)


@router_public.post("/webhooks/instagram")
async def receive_instagram_webhook_root(
    request: Request,
    x_hub_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    return await _receive_instagram_webhook_impl(request, x_hub_signature)



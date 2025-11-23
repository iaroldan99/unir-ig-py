from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.messages import (
    Conversation,
    SendMessageRequest,          # lo vamos a ampliar para compat
    SendMessageResponse,
)
from app.services.instagram_client import InstagramClient, get_instagram_client
from app.services.token_store import TokenStore, get_token_store

# --------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------
router = APIRouter()
router_public = APIRouter()   # <-- público para recibir desde el Core

# --------------------------------------------------------------------
# Endpoints "privados" (postman / backoffice)
# --------------------------------------------------------------------
@router.get("/conversations", response_model=List[Conversation])
async def list_conversations(
    ig: InstagramClient = Depends(get_instagram_client),
    token_store: TokenStore = Depends(get_token_store),
):
    tokens = await token_store.get_tokens()
    if not tokens:
        raise HTTPException(status_code=401, detail="No autenticado")
    return await ig.list_conversations(tokens)


@router.post("/send", response_model=SendMessageResponse)
async def send_message(
    payload: SendMessageRequest,
    ig: InstagramClient = Depends(get_instagram_client),
    token_store: TokenStore = Depends(get_token_store),
):
    """Envía usando el formato nativo (recipient_id + text)."""
    return await _do_send(payload, ig, token_store)

# --------------------------------------------------------------------
# Endpoint PÚBLICO para el Core
#   - URL:  POST /send/{channel}
#   - Body aceptado: 
#       a) { "recipient_id": "...", "text": "..." }        (nativo)
#       b) { "to": "...", "message": "...", ... }          (core)
# --------------------------------------------------------------------
@router_public.post("/send/{channel}", response_model=SendMessageResponse)
async def send_message_public(
    channel: str,
    payload: SendMessageRequest,   # mismo modelo, pero con alias de compat
    ig: InstagramClient = Depends(get_instagram_client),
    token_store: TokenStore = Depends(get_token_store),
):
    if channel.lower() != "instagram":
        raise HTTPException(status_code=404, detail="Canal no soportado por este servicio")
    return await _do_send(payload, ig, token_store)

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
async def _do_send(
    payload: SendMessageRequest,
    ig: InstagramClient,
    token_store: TokenStore,
) -> SendMessageResponse:
    """
    Normaliza el body (acepta core o nativo) y llama al cliente IG.
    """
    tokens = await token_store.get_tokens()
    if not tokens:
        raise HTTPException(status_code=401, detail="No autenticado")

    # Normalización: prioriza el formato nativo; cae al formato del Core
    recipient_id = payload.recipient_id or payload.to
    text = payload.text or payload.message

    if not recipient_id or not text:
        raise HTTPException(
            status_code=422,
            detail="Faltan campos: usa recipient_id+text o to+message",
        )

    # Construye un payload "nativo" para el cliente IG
    normalized = SendMessageRequest(recipient_id=recipient_id, text=text)
    return await ig.send_message(tokens, normalized)
from typing import List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
import httpx

from app.schemas.messages import Conversation, SendMessageRequest, SendMessageResponse
from app.services.instagram_client import InstagramClient, get_instagram_client
from app.services.token_store import TokenStore, get_token_store
from app.core.config import settings


router = APIRouter()


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
    tokens = await token_store.get_tokens()
    if not tokens:
        raise HTTPException(status_code=401, detail="No autenticado")
    resp: SendMessageResponse = await ig.send_message(tokens, payload)

    # Notificar al Core (outbound) si está configurado
    if settings.CORE_API_URL:
        try:
            ts_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            unified_event = {
                "channel": "instagram",
                "sender": (tokens.page_id or ""),  # la página como emisor
                "message": payload.text,
                "timestamp": ts_iso,
                "message_id": resp.message_id,
                "message_type": "text",
                "sender_name": "",
            }
            url = settings.CORE_API_URL.rstrip("/") + "/api/v1/messages/unified"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json=unified_event)
        except Exception:
            # No bloquear la respuesta al cliente si el Core falla
            pass

    return resp



from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.messages import Conversation, SendMessageRequest, SendMessageResponse
from app.services.instagram_client import InstagramClient, get_instagram_client
from app.services.token_store import TokenStore, get_token_store


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
    return await ig.send_message(tokens, payload)



import logging
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.errors import AppError
from app.services.token_store import TokenStore, get_token_store
from app.services.instagram_client import InstagramClient, get_instagram_client


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login")
async def login():
    if not settings.APP_ID or not settings.REDIRECT_URI:
        raise HTTPException(status_code=500, detail="APP_ID o REDIRECT_URI no configurados")

    # Scopes recomendados (sin pages_messaging deprecado)
    scopes = [
        "instagram_basic",
        "instagram_manage_messages",
        "pages_show_list",
        "pages_manage_metadata",
    ]

    params = {
        "client_id": settings.APP_ID,
        "redirect_uri": settings.REDIRECT_URI,
        "scope": ",".join(scopes),
        "response_type": "code",
    }

    version = settings.GRAPH_API_VERSION
    if not version.startswith("v"):
        version = "v" + version

    url = f"https://www.facebook.com/{version}/dialog/oauth?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@router.get("/instagram/callback")
async def callback(
    code: str,
    token_store: TokenStore = Depends(get_token_store),
    ig: InstagramClient = Depends(get_instagram_client),
):
    try:
        tokens = await ig.exchange_code_for_tokens(code)
        await token_store.save_tokens(tokens)
        return {"detail": "ok", "scopes": tokens.scopes}
    except AppError as e:  # pragma: no cover - flow de redireccion
        logger.exception("OAuth callback error")
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/me")
async def me(
    token_store: TokenStore = Depends(get_token_store),
):
    tokens = await token_store.get_tokens()
    if not tokens:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {
        "page_id": tokens.page_id,
        "ig_user_id": tokens.ig_user_id,
        "scopes": tokens.scopes,
    }



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


@router.get("/debug/me-accounts")
async def debug_me_accounts(
    token_store: TokenStore = Depends(get_token_store),
    ig: InstagramClient = Depends(get_instagram_client),
):
    """
    Diagnóstico: usa el user access token guardado para consultar
    /me/accounts y, por cada página, connected_instagram_account.
    """
    tokens = await token_store.get_tokens()
    if not tokens or not getattr(tokens, "user_access_token", None):
        raise HTTPException(
            status_code=401,
            detail="No autenticado (no hay user token guardado)",
        )
    data = await ig.debug_probe(tokens.user_access_token)
    return data


@router.get("/login")
async def login():
    """
    Redirige al diálogo OAuth de Facebook con scopes adecuados para IG Messaging.
    """
    if not settings.APP_ID or not settings.REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="APP_ID o REDIRECT_URI no configurados",
        )

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
        # "auth_type": "rerequest",  # opcional: forzar re-consent en pruebas
        # "state": "debug123",       # opcional
    }

    version = settings.GRAPH_API_VERSION or "v19.0"
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
    """
    Recibe el code de OAuth, intercambia por tokens y persiste PAGE token + IG user id.
    """
    try:
        tokens = await ig.exchange_code_for_tokens(code)
        await token_store.save_tokens(tokens)
        return {"detail": "ok", "scopes": tokens.scopes}
    except AppError as e:  # pragma: no cover (flujo de redirección)
        logger.exception("OAuth callback error")
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/me")
async def me(token_store: TokenStore = Depends(get_token_store)):
    """
    Devuelve datos básicos de la sesión guardada.
    """
    tokens = await token_store.get_tokens()
    if not tokens:
        raise HTTPException(status_code=401, detail="No autenticado")
    return {
        "page_id": tokens.page_id,
        "ig_user_id": tokens.ig_user_id,
        "scopes": tokens.scopes,
    }

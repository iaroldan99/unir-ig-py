# app/services/instagram_client.py
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.schemas.messages import (
    Conversation, ConversationMessage,
    SendMessageRequest, SendMessageResponse
)

logger = logging.getLogger(__name__)


class OAuthTokens:
    def __init__(
        self,
        access_token: str,
        page_id: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        user_access_token: Optional[str] = None,  # útil para debug
    ):
        self.access_token = access_token          # PAGE ACCESS TOKEN
        self.page_id = page_id
        self.ig_user_id = ig_user_id
        self.scopes = scopes or []
        self.user_access_token = user_access_token

    def model_dump(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "page_id": self.page_id,
            "ig_user_id": self.ig_user_id,
            "scopes": self.scopes,
            "user_access_token": self.user_access_token,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "OAuthTokens":
        return OAuthTokens(
            access_token=data.get("access_token", ""),
            page_id=data.get("page_id"),
            ig_user_id=data.get("ig_user_id"),
            scopes=data.get("scopes", []),
            user_access_token=data.get("user_access_token"),
        )


class InstagramClient:
    def __init__(self):
        # Usa la versión con prefijo "v", ej: v19.0
        version = settings.GRAPH_API_VERSION or "v19.0"
        if not version.startswith("v"):
            version = "v" + version
        self.version = version
        self.base_graph_url = f"https://graph.facebook.com/{self.version}"

    async def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            url = f"{self.base_graph_url}{path}"
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()

    async def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        # 1) Intercambio de code -> USER ACCESS TOKEN
        token_url = f"{self.base_graph_url}/oauth/access_token"
        params = {
            "client_id": settings.APP_ID,
            "client_secret": settings.APP_SECRET,
            "redirect_uri": settings.REDIRECT_URI,
            "code": code,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(token_url, params=params)
        if resp.status_code != 200:
            raise AppError("No se pudo intercambiar el code por token", 400)
        data = resp.json()
        user_access_token = data.get("access_token")
        if not user_access_token:
            raise AppError("Respuesta inválida de OAuth", 400)

        # 2) Listar páginas del usuario (obtengo PAGE_ID + PAGE_ACCESS_TOKEN)
        me_accounts = await self._get(
            "/me/accounts",
            {"fields": "id,name,access_token", "access_token": user_access_token},
        )
        pages = me_accounts.get("data", [])
        if not pages:
            raise AppError("El usuario no administra páginas", 400)

        # 3) Para cada página, verificar IG vinculado
        selected = None
        for p in pages:
            pid = p["id"]
            page_token = p.get("access_token")
            try:
                page_meta = await self._get(
                    f"/{pid}",
                    {
                        "fields": "connected_instagram_account",
                        "access_token": page_token or user_access_token,
                    },
                )
                ig_obj = page_meta.get("connected_instagram_account")
                if ig_obj and ig_obj.get("id"):
                    selected = {
                        "page_id": pid,
                        "page_access_token": page_token,
                        "ig_user_id": ig_obj["id"],
                    }
                    break
            except httpx.HTTPStatusError:
                # sigue con la próxima página
                continue

        if not selected:
            raise AppError("No hay página con cuenta de Instagram vinculada", 400)

        return OAuthTokens(
            access_token=selected["page_access_token"],  # PAGE TOKEN
            page_id=selected["page_id"],
            ig_user_id=selected["ig_user_id"],
            scopes=[
                "instagram_basic",
                "instagram_manage_messages",
                "pages_show_list",
                "pages_manage_metadata",
            ],
            user_access_token=user_access_token,
        )

    # --- Opcional: endpoint de diagnóstico usa estos ---
    async def debug_probe(self, user_access_token: str) -> Dict[str, Any]:
        me_accounts = await self._get(
            "/me/accounts",
            {"fields": "id,name,access_token", "access_token": user_access_token},
        )
        pages_out = []
        for p in me_accounts.get("data", []):
            pid = p["id"]
            pa = p.get("access_token")
            meta = await self._get(
                f"/{pid}",
                {
                    "fields": "connected_instagram_account",
                    "access_token": pa or user_access_token,
                },
            )
            pages_out.append(
                {
                    "id": pid,
                    "name": p.get("name"),
                    "connected_instagram_account": meta.get("connected_instagram_account"),
                }
            )
        return {"me_accounts": me_accounts, "pages_probe": pages_out}

    # --- tus métodos de mensajes se quedan igual ---


_instagram_client: Optional[InstagramClient] = None

def get_instagram_client() -> InstagramClient:
    global _instagram_client
    if _instagram_client is None:
        _instagram_client = InstagramClient()
    return _instagram_client

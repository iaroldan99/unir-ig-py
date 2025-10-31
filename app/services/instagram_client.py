# app/services/instagram_client.py
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

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

        # Fallback: algunas cuentas bajo Business Manager no devuelven páginas en /me/accounts.
        # Intentar via /me?fields=businesses -> /{business}/owned_pages y /{business}/client_pages
        if not pages:
            try:
                me_with_businesses = await self._get(
                    "/me",
                    {"fields": "businesses{id,name}", "access_token": user_access_token},
                )
                businesses = (
                    (me_with_businesses.get("businesses") or {}).get("data", [])
                )
                aggregated_pages: List[Dict[str, Any]] = []
                for biz in businesses:
                    bid = biz.get("id")
                    if not bid:
                        continue
                    for rel in ("owned_pages", "client_pages"):
                        try:
                            rel_pages = await self._get(
                                f"/{bid}/{rel}",
                                {
                                    "fields": "id,name,access_token",
                                    "access_token": user_access_token,
                                },
                            )
                            aggregated_pages.extend(rel_pages.get("data", []))
                        except httpx.HTTPStatusError:
                            continue
                if aggregated_pages:
                    pages = aggregated_pages
            except httpx.HTTPStatusError:
                # Si falla el fallback, seguimos con la validación normal
                pass

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

    # --- Mensajería IG ---

    async def list_conversations(self, tokens: OAuthTokens) -> List[Conversation]:
        if not tokens.ig_user_id or not tokens.access_token:
            raise AppError("Faltan tokens para listar conversaciones", 400)

        params = {
            "platform": "instagram",
            "fields": "participants,messages.limit(1){id,message,from,to,created_time}",
            "access_token": tokens.access_token,
        }
        # Intento 1: por IG User ID (recomendado para IG Messaging)
        try:
            data = await self._get(f"/{tokens.ig_user_id}/conversations", params)
        except httpx.HTTPStatusError as e:
            # Fallback 2: algunas cuentas requieren consultar por PAGE ID
            try:
                data = await self._get(f"/{tokens.page_id}/conversations", params)
            except httpx.HTTPStatusError as e2:
                # Propagar mensaje claro de Graph
                try:
                    err = e2.response.json()
                    msg = (err.get("error") or {}).get("message") or str(err)
                except Exception:
                    msg = e2.response.text
                logger.error("list_conversations 400: %s", msg)
                raise AppError(f"Error de Graph al listar conversaciones: {msg}", 400)
        items = []
        for conv in data.get("data", []):
            participants = [p.get("id") for p in (conv.get("participants", {}).get("data", [])) if p.get("id")]
            last = None
            msgs = conv.get("messages", {}).get("data", [])
            if msgs:
                m = msgs[0]
                # created_time formato ISO8601 -> epoch
                ts = 0
                ct = m.get("created_time")
                if ct:
                    try:
                        ts = int(datetime.fromisoformat(ct.replace("Z", "+00:00")).timestamp())
                    except Exception:
                        ts = 0
                last = ConversationMessage(
                    id=m.get("id", ""),
                    from_id=(m.get("from") or {}).get("id", ""),
                    to_id=((m.get("to") or {}).get("data", [{}])[0].get("id", "")),
                    text=m.get("message"),
                    timestamp=ts,
                )
            items.append(Conversation(id=conv.get("id", ""), participants=participants, last_message=last))
        return items

    async def send_message(self, tokens: OAuthTokens, payload: SendMessageRequest) -> SendMessageResponse:
        if not tokens.access_token:
            raise AppError("No hay PAGE ACCESS TOKEN configurado", 401)

        url = f"{self.base_graph_url}/me/messages"
        params = {"access_token": tokens.access_token}
        body = {
            "recipient": {"id": payload.recipient_id},
            "message": {"text": payload.text},
            "messaging_type": "RESPONSE",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, params=params, json=body)
            if resp.status_code != 200:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                logger.error("send_message error (%s): %s", resp.status_code, err)
                # Mensaje específico cuando el recipient es inválido
                if isinstance(err, dict):
                    gmsg = (err.get("error") or {}).get("message")
                else:
                    gmsg = str(err)
                raise AppError(f"Error enviando mensaje: {gmsg}", 400)
            data = resp.json()
            return SendMessageResponse(
                message_id=data.get("message_id", ""),
                recipient_id=data.get("recipient_id", payload.recipient_id),
            )


_instagram_client: Optional[InstagramClient] = None

def get_instagram_client() -> InstagramClient:
    global _instagram_client
    if _instagram_client is None:
        _instagram_client = InstagramClient()
    return _instagram_client

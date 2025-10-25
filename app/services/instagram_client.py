import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.schemas.messages import Conversation, ConversationMessage, SendMessageRequest, SendMessageResponse


logger = logging.getLogger(__name__)


class OAuthTokens:
    def __init__(self, access_token: str, page_id: Optional[str] = None, ig_user_id: Optional[str] = None, scopes: Optional[List[str]] = None):
        self.access_token = access_token
        self.page_id = page_id
        self.ig_user_id = ig_user_id
        self.scopes = scopes or []

    def model_dump(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "page_id": self.page_id,
            "ig_user_id": self.ig_user_id,
            "scopes": self.scopes,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "OAuthTokens":
        return OAuthTokens(
            access_token=data.get("access_token", ""),
            page_id=data.get("page_id"),
            ig_user_id=data.get("ig_user_id"),
            scopes=data.get("scopes", []),
        )


class InstagramClient:
    def __init__(self):
        self.base_graph_url = f"https://graph.facebook.com/v{settings.GRAPH_API_VERSION}"

    async def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
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
            access_token = data.get("access_token")
            if not access_token:
                raise AppError("Respuesta inválida de OAuth", 400)

        # Obtener páginas del usuario para IG Messaging (requiere Page access token)
        async with httpx.AsyncClient(timeout=20) as client:
            me_accounts = await client.get(
                f"{self.base_graph_url}/me/accounts",
                params={"access_token": access_token},
            )
            if me_accounts.status_code != 200:
                raise AppError("No se pudieron obtener las páginas del usuario", 400)
            accounts = me_accounts.json().get("data", [])
            page = next((a for a in accounts if "instagram_business_account" in a), None)
            if not page:
                raise AppError("No hay página con cuenta de Instagram vinculada", 400)

            page_access_token = page.get("access_token")
            page_id = page.get("id")
            ig_user_id = page.get("instagram_business_account", {}).get("id")

        return OAuthTokens(access_token=page_access_token, page_id=page_id, ig_user_id=ig_user_id, scopes=["pages_messaging", "instagram_manage_messages"])

    async def list_conversations(self, tokens: "OAuthTokens") -> List[Conversation]:
        # Simplificado: listar conversaciones del inbox
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.base_graph_url}/{tokens.page_id}/conversations",
                params={"platform": "instagram", "access_token": tokens.access_token, "fields": "participants,messages.limit(1){from,to,message,created_time}"},
            )
            if resp.status_code != 200:
                raise AppError("Error al listar conversaciones", 400)
            data = resp.json().get("data", [])

        conversations: List[Conversation] = []
        for c in data:
            last = None
            messages = c.get("messages", {}).get("data", [])
            if messages:
                m = messages[0]
                last = ConversationMessage(
                    id=m.get("id", ""),
                    from_id=m.get("from", {}).get("id", ""),
                    to_id=m.get("to", {}).get("data", [{}])[0].get("id", ""),
                    text=m.get("message"),
                    timestamp=int(__import__("datetime").datetime.fromisoformat(m.get("created_time").replace("Z", "+00:00")).timestamp()),
                )
            participants = [p.get("id", "") for p in c.get("participants", {}).get("data", [])]
            conversations.append(Conversation(id=c.get("id", ""), participants=participants, last_message=last))
        return conversations

    async def send_message(self, tokens: "OAuthTokens", payload: SendMessageRequest) -> SendMessageResponse:
        endpoint = f"{self.base_graph_url}/{tokens.page_id}/messages"
        body = {
            "recipient": {"id": payload.recipient_id},
            "message": {"text": payload.text},
            "messaging_type": "RESPONSE",
            "tag": "HUMAN_AGENT",
            "platform": "instagram",
            "access_token": tokens.access_token,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(endpoint, data=body)
            if resp.status_code not in (200, 201):
                raise AppError("No se pudo enviar el mensaje", 400)
            data = resp.json()
        return SendMessageResponse(message_id=str(data.get("message_id")), recipient_id=payload.recipient_id)


_instagram_client: Optional[InstagramClient] = None


def get_instagram_client() -> InstagramClient:
    global _instagram_client
    if _instagram_client is None:
        _instagram_client = InstagramClient()
    return _instagram_client



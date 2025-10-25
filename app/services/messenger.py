# app/services/messenger.py
import httpx
from app.core.config import settings

GRAPH_BASE = f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}"

async def send_ig_message(psid: str, text: str):
    """
    Envía un DM por Messenger API for Instagram usando el Page Access Token.
    psid: page-scoped ID del usuario que te escribió (viene en el webhook).
    """
    url = f"{GRAPH_BASE}/me/messages"
    params = {"access_token": settings.PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text},
        "messaging_type": "RESPONSE",  # libre dentro de 24h desde el último msg del usuario
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, params=params, json=payload)
        # útil en desarrollo:
        # print("send_ig_message", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}"

async def send_ig_message(psid: str, text: str):
    """
    Envía un DM por Messenger API for Instagram usando el Page Access Token.
    psid: page-scoped ID (viene en el webhook).
    """
    url = f"{GRAPH_BASE}/me/messages"
    params = {"access_token": settings.PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text},
        "messaging_type": "RESPONSE",  # libre dentro de 24h desde el último msg del usuario
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, params=params, json=payload)

        if resp.status_code != 200:
            # Log detallado para depurar permisos / token
            try:
                data = resp.json()
            except Exception:
                data = resp.text
            logger.error("❌ Graph error (%s): %s", resp.status_code, data)
            resp.raise_for_status()

        data = resp.json()
        logger.info("📤 Enviado a %s | respuesta: %s", psid, data)
        return data

import json
import os
from typing import Optional

from app.core.config import settings
from app.services.instagram_client import OAuthTokens


class TokenStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def save_tokens(self, tokens: OAuthTokens) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(tokens.model_dump(), f)

    async def get_tokens(self) -> Optional[OAuthTokens]:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("access_token"):
                return None
            return OAuthTokens.from_dict(data)
        except Exception:
            return None


_token_store: Optional[TokenStore] = None


def get_token_store() -> TokenStore:
    global _token_store
    if _token_store is None:
        _token_store = TokenStore(settings.TOKEN_STORE_PATH)
    return _token_store



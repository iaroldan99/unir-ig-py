from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ig-service-api"
    VERSION: str = "0.1.0"
    ENV: str = "development"
    PORT: int = 8000

    # Meta App / Graph API (admite variables alternativas usadas por el usuario)
    APP_ID: str = Field(default="", env=["APP_ID", "INSTAGRAM_CLIENT_ID"])
    APP_SECRET: str = Field(default="", env=["APP_SECRET", "INSTAGRAM_CLIENT_SECRET"])
    VERIFY_TOKEN: str = Field(default="", env=["VERIFY_TOKEN", "INSTAGRAM_VERIFY_TOKEN"])
    REDIRECT_URI: str = Field(default="http://localhost:8000/auth/instagram/callback", env=["REDIRECT_URI", "INSTAGRAM_REDIRECT_URI"])
    GRAPH_API_VERSION: str = "19.0"
    INSTAGRAM_VERIFY_TOKEN: str = Field(default="demo_token")
    INSTAGRAM_PAGE_ID: str = Field(default="")
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    # Token store
    TOKEN_STORE_PATH: str = "data/tokens.json"

    CORE_UNIFIED_URL: str = Field(default="", env="CORE_UNIFIED_URL")  # p.ej. https://core.ngrok-free.app/api/v1/messages/unified
    CORE_API_KEY: str = Field(default="", env="CORE_API_KEY")
    PAGE_ACCESS_TOKEN: str = Field(default="", env=["PAGE_ACCESS_TOKEN"])
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()



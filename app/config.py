# app/config.py
from pydantic import BaseSettings

class Settings(BaseSettings):
    APP_ID: str
    APP_SECRET: str
    VERIFY_TOKEN: str  # o INSTAGRAM_VERIFY_TOKEN mapeado por .env
    GRAPH_API_VERSION: str = "v24.0"
    PAGE_ACCESS_TOKEN: str  # <-- IMPRESCINDIBLE

    class Config:
        env_file = ".env"
        # opcional: env_file_encoding = "utf-8"

settings = Settings()

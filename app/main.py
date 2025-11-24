from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.errors import register_exception_handlers
from app.api.routes import auth, messages, webhook

def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Tu frontend Vite
        "http://localhost:5173",      # Puerto alternativo de Vite
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
    )


    register_exception_handlers(app)

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(messages.router, prefix="/messages", tags=["messages"])
    app.include_router(messages.router_public, tags=["messages"])  # <-- agrega ESTA línea
    # Exponer endpoints del webhook únicamente desde el módulo webhook, sin duplicar
    app.include_router(webhook.router, prefix="/webhook", tags=["webhook"])  # compat
    app.include_router(webhook.router_public, tags=["webhook"])  # expone /webhooks/instagram

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(settings.PORT), reload=True)



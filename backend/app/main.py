"""FastAPI application entry point."""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, settings

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]
)


def create_app(app_settings: Settings) -> FastAPI:
    application = FastAPI(title="Document Copilot API")
    application.state.settings = app_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).rstrip("/") for origin in app_settings.allowed_origins
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app(settings)

print(settings.openai_embedding_model)
print(settings.openai_embedding_dimensions)
print(settings.allowed_origins)

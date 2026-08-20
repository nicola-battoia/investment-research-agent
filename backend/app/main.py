"""FastAPI application entry point."""

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest import APIError

from app.api.chat import router as chat_router
from app.config import Settings, settings
from app.database.chats import (
    ChatPositionConflictError,
    ChatThreadForbiddenError,
    ChatThreadNotFoundError,
)

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

    application.include_router(chat_router)

    @application.exception_handler(ChatThreadNotFoundError)
    async def thread_not_found(
        _request: Request,
        _error: ChatThreadNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": "Chat thread not found"}
        )

    @application.exception_handler(ChatThreadForbiddenError)
    async def thread_forbidden(
        _request: Request,
        _error: ChatThreadForbiddenError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": "You do not have access to this chat thread"},
        )

    @application.exception_handler(ChatPositionConflictError)
    async def position_conflict(
        _request: Request,
        _error: ChatPositionConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Another message is already being sent"},
        )

    @application.exception_handler(APIError)
    async def database_error(_request: Request, _error: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": "The chat database request failed"},
        )

    return application


app = create_app(settings)

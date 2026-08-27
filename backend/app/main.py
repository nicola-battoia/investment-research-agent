"""FastAPI application entry point."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from postgrest import APIError

from app.api.chat import router as chat_router
from app.assistant import DocumentAssistant, create_document_assistant
from app.config import Settings, settings
from app.database.chats import (
    ChatPositionConflictError,
    ChatThreadForbiddenError,
    ChatThreadNotFoundError,
)
from app.logging_config import configure_logging

configure_logging(settings)
logger = structlog.get_logger()


def create_app(
    app_settings: Settings,
    *,
    openai_client: AsyncOpenAI | None = None,
    document_assistant: DocumentAssistant | None = None,
) -> FastAPI:
    owns_openai_client = openai_client is None
    shared_openai_client = openai_client or AsyncOpenAI(
        api_key=app_settings.openai_api_key.get_secret_value(),
        max_retries=app_settings.openai_http_max_retries,
    )
    shared_assistant = document_assistant or create_document_assistant(
        app_settings,
        shared_openai_client,
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        yield
        if owns_openai_client:
            await shared_openai_client.close()

    application = FastAPI(title="Document Copilot API", lifespan=lifespan)
    application.state.settings = app_settings
    application.state.openai_client = shared_openai_client
    application.state.document_assistant = shared_assistant
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
        request: Request,
        error: ChatThreadNotFoundError,
    ) -> JSONResponse:
        _log_handled_chat_error(request, error, "thread_missing", 404)
        return JSONResponse(
            status_code=404, content={"detail": "Chat thread not found"}
        )

    @application.exception_handler(ChatThreadForbiddenError)
    async def thread_forbidden(
        request: Request,
        error: ChatThreadForbiddenError,
    ) -> JSONResponse:
        _log_handled_chat_error(request, error, "thread_forbidden", 403)
        return JSONResponse(
            status_code=403,
            content={"detail": "You do not have access to this chat thread"},
        )

    @application.exception_handler(ChatPositionConflictError)
    async def position_conflict(
        request: Request,
        error: ChatPositionConflictError,
    ) -> JSONResponse:
        _log_handled_chat_error(request, error, "turn_conflict", 409)
        return JSONResponse(
            status_code=409,
            content={"detail": "Another message is already being sent"},
        )

    @application.exception_handler(APIError)
    async def database_error(request: Request, error: APIError) -> JSONResponse:
        _log_handled_chat_error(request, error, "database_unavailable", 502)
        return JSONResponse(
            status_code=502,
            content={"detail": "The chat database request failed"},
        )

    return application


def _log_handled_chat_error(
    request: Request,
    error: Exception,
    error_code: str,
    http_status_code: int,
) -> None:
    trace = getattr(request.state, "assistant_trace", None)
    trace_id = getattr(trace, "trace_id", None)
    failed_after_stage = getattr(trace, "last_stage", "request.dispatch")
    route = getattr(request.scope.get("route"), "path", "unmatched")
    if trace is not None:
        trace.emit(
            "chat_request_failed",
            "request.failed",
            level="warning",
            operational=True,
            method=request.method,
            route=route,
            http_status_code=http_status_code,
            error_class=type(error).__name__,
            error_code=error_code,
            failed_after_stage=failed_after_stage,
        )
    else:
        logger.warning(
            "chat_request_failed",
            trace_id=trace_id,
            method=request.method,
            route=route,
            http_status_code=http_status_code,
            error_class=type(error).__name__,
            error_code=error_code,
            failed_after_stage=failed_after_stage,
        )


app = create_app(settings)

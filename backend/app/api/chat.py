"""Owned chat thread CRUD and complete grounded assistant streaming."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import field_validator

from app.auth.dependencies import AuthenticatedContext, get_authenticated_context
from app.chat.messages import (
    ApiModel,
    ChatStreamRequest,
    UIMessageResponse,
    stored_messages_to_ui,
    to_internal_user_message,
)
from app.chat.orchestrator import ChatTurnOrchestrator
from app.chat.streaming import chat_turn_events
from app.database import chats

router = APIRouter(prefix="/chat", tags=["chat"])

ChatContext = Annotated[AuthenticatedContext, Depends(get_authenticated_context)]


class ThreadSummary(ApiModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ThreadDetail(ApiModel):
    thread: ThreadSummary
    messages: list[UIMessageResponse]


class CreateThreadRequest(ApiModel):
    title: str = "New chat"

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validated_title(value)


class RenameThreadRequest(ApiModel):
    title: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validated_title(value)


@router.get("/threads", response_model=list[ThreadSummary])
async def get_threads(context: ChatContext) -> list[ThreadSummary]:
    rows = await chats.list_threads(context.supabase, UUID(context.user.id))
    return [_thread_summary(row) for row in rows]


@router.post(
    "/threads",
    response_model=ThreadSummary,
    status_code=status.HTTP_201_CREATED,
)
async def post_thread(
    payload: CreateThreadRequest,
    context: ChatContext,
) -> ThreadSummary:
    row = await chats.create_thread(
        context.supabase,
        UUID(context.user.id),
        payload.title,
    )
    return _thread_summary(row)


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(
    thread_id: UUID,
    request: Request,
    context: ChatContext,
) -> ThreadDetail:
    thread, messages, citations = await chats.load_thread(
        context.supabase,
        request.app.state.settings,
        thread_id,
        UUID(context.user.id),
    )
    return ThreadDetail(
        thread=_thread_summary(thread),
        messages=stored_messages_to_ui(messages, citations),
    )


@router.patch("/threads/{thread_id}", response_model=ThreadSummary)
async def patch_thread(
    thread_id: UUID,
    payload: RenameThreadRequest,
    request: Request,
    context: ChatContext,
) -> ThreadSummary:
    row = await chats.rename_thread(
        context.supabase,
        request.app.state.settings,
        thread_id,
        UUID(context.user.id),
        payload.title,
    )
    return _thread_summary(row)


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_thread(
    thread_id: UUID,
    request: Request,
    context: ChatContext,
) -> Response:
    await chats.delete_thread(
        context.supabase,
        request.app.state.settings,
        thread_id,
        UUID(context.user.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/stream")
async def stream_chat(
    payload: ChatStreamRequest,
    request: Request,
    context: ChatContext,
) -> StreamingResponse:
    user_id = UUID(context.user.id)
    orchestrator = ChatTurnOrchestrator(
        settings=request.app.state.settings,
        supabase=context.supabase,
        openai_client=request.app.state.openai_client,
        assistant=request.app.state.document_assistant,
    )
    prepared = await orchestrator.prepare(
        thread_id=payload.id,
        user_id=user_id,
        user_message=to_internal_user_message(payload.message),
    )
    return StreamingResponse(
        chat_turn_events(
            request=request,
            orchestrator=orchestrator,
            turn=prepared,
            timeout_seconds=request.app.state.settings.chat_turn_timeout_seconds,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )


def _thread_summary(row: dict[str, object]) -> ThreadSummary:
    return ThreadSummary.model_validate(row)


def _validated_title(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Thread title cannot be empty")
    if len(value) > 200:
        raise ValueError("Thread title cannot exceed 200 characters")
    return value

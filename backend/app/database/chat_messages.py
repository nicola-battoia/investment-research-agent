"""Ordered user and assistant messages."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.chat_threads import ChatThread
    from app.database.message_citations import MessageCitation


class ChatMessage(TimestampMixin, Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="valid_role",
        ),
        CheckConstraint("position >= 0", name="non_negative_position"),
        UniqueConstraint(
            "thread_id",
            "position",
            name="uq_chat_messages_thread_position",
        ),
        Index("ix_chat_messages_thread_created_at", "thread_id", "created_at"),
        Index(
            "uq_chat_messages_thread_client_message_id",
            "thread_id",
            sql_text("(message_data ->> 'clientMessageId')"),
            unique=True,
            postgresql_where=sql_text(
                "role = 'user' AND message_data ? 'clientMessageId'"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    thread_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_data: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
        nullable=False,
    )
    model_usage: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    thread: Mapped["ChatThread"] = relationship(back_populates="messages")
    citations: Mapped[list["MessageCitation"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MessageCitation.citation_index",
    )

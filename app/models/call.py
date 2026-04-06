"""Dynamic call state — Microsoft pattern (NOT a rigid FSM).

Microsoft's CallStateModel is a flexible data container that adapts to
conversation flow. It does NOT enforce state transitions. The LLM decides
what to do based on conversation history and available tools.

OptiBot v2: same pattern, with dossier-specific fields.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.models.dossier import Dossier
from app.models.message import Message, Persona


class CallState(BaseModel):
    """Flexible call state — adapts to conversation, not enforced transitions.

    Attributes:
        call_sid: Unique call identifier (from LiveKit/Twilio)
        tenant_id: Which optician this call belongs to
        dossier: The reimbursement case being discussed
        mutuelle: Which health insurer we're calling
        messages: Conversation history (auto-merge consecutive same-role)
        extracted: Structured data extracted during the call
        phase: Loose phase indicator (ivr → conversation → wrap_up)
        hold_detected: Whether hold music/silence was detected
        ivr_attempts: Number of DTMF presses attempted
        rag_context: Pre-loaded context from similar past calls
    """

    call_sid: str
    tenant_id: str
    dossier: Dossier
    mutuelle: str

    # Conversation history
    messages: list[Message] = []

    # Extracted data (accumulates during call)
    extracted: dict[str, Any] = {}

    # Call metadata (loose, not enforced)
    phase: str = "ivr"
    hold_detected: bool = False
    ivr_attempts: int = 0
    tools_called: list[str] = []

    # RAG context (loaded during dial phase)
    rag_context: dict[str, Any] = {}

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_interaction: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_message(self, role: Persona, content: str, **kwargs) -> None:
        """Add message with auto-merge of consecutive same-role messages.

        Microsoft pattern: consecutive messages from same persona are consolidated.
        This reduces token usage and improves LLM comprehension.
        """
        if self.messages and self.messages[-1].role == role and role != Persona.TOOL:
            self.messages[-1].content += f" {content}"
            self.messages[-1].created_at = datetime.now(timezone.utc)
        else:
            self.messages.append(Message(role=role, content=content, **kwargs))
        self.last_interaction = datetime.now(timezone.utc)

    def get_llm_messages(self) -> list[dict]:
        """Convert messages to LLM-compatible format."""
        return [m.to_llm_dict() for m in self.messages]

    def record_extraction(self, key: str, value: Any) -> None:
        """Record extracted data from mutuelle agent's response."""
        self.extracted[key] = value

    def record_tool_call(self, tool_name: str) -> None:
        """Track which tools have been called this call."""
        self.tools_called.append(tool_name)

    @property
    def duration_seconds(self) -> float:
        """Call duration in seconds."""
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()

    @property
    def turn_count(self) -> int:
        """Number of conversation turns (user messages)."""
        return sum(1 for m in self.messages if m.role == Persona.HUMAN)

    def to_redis_dict(self) -> dict:
        """Serialize for Redis persistence (crash recovery)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_redis_dict(cls, data: dict) -> CallState:
        """Deserialize from Redis."""
        return cls.model_validate(data)

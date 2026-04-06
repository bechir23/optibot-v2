"""Message model — Microsoft pattern.

Pydantic-based with persona, timestamps, auto-merge of consecutive same-role messages.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class Persona(StrEnum):
    SYSTEM = "system"
    ASSISTANT = "assistant"  # Our bot
    HUMAN = "user"           # Mutuelle agent
    TOOL = "tool"


class Message(BaseModel):
    """A single message in the conversation."""

    role: Persona
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_llm_dict(self) -> dict:
        """Convert to OpenAI-compatible message dict for LLM API."""
        d = {"role": self.role.value, "content": self.content}
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d

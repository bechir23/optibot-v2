from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.models.session_state import CallSessionState


class SessionRouter:
    """Small policy layer that keeps handoff construction consistent."""

    def __init__(
        self,
        *,
        session_data: CallSessionState,
        caller_agent_kwargs: dict[str, Any],
    ) -> None:
        self._session_data = session_data
        self._caller_agent_kwargs = dict(caller_agent_kwargs)

    def should_use_ivr(self, known_ivr: dict[str, Any] | None, force_ivr: bool) -> bool:
        return force_ivr or known_ivr is not None

    def build_call_agent(self, *, chat_ctx=None):
        from app.agents.outbound_caller import OutboundCallerAgent

        kwargs = self._caller_kwargs(chat_ctx=chat_ctx)
        return OutboundCallerAgent(**kwargs)

    def build_ivr_agent(
        self,
        *,
        target_service: str,
        max_attempts: int,
        known_ivr_tree: dict[str, Any] | None,
        chat_ctx=None,
    ):
        from app.agents.ivr_navigator import IVRNavigatorAgent

        return IVRNavigatorAgent(
            target_service=target_service,
            max_attempts=max_attempts,
            known_ivr_tree=known_ivr_tree,
            tenant_id=self._session_data.tenant_id,
            mutuelle=self._session_data.mutuelle,
            caller_agent_kwargs=self._caller_kwargs(chat_ctx=chat_ctx),
            session_data=self._session_data,
            session_router=self,
            chat_ctx=chat_ctx,
        )

    def can_handoff(self) -> bool:
        return self._session_data.handoff_depth < self._session_data.max_handoff_depth

    def note_handoff(self) -> bool:
        return self._session_data.record_handoff()

    def handoff_context_text(self) -> str:
        parts: list[str] = []
        if self._session_data.ivr_path:
            parts.append(f"Parcours IVR: {' > '.join(self._session_data.ivr_path)}")
        if self._session_data.ivr_transcript:
            latest = " | ".join(self._session_data.ivr_transcript[-4:])
            parts.append(f"Historique IVR: {latest}")
        if self._session_data.unresolved_goals:
            parts.append(
                "Objectifs en attente: " + "; ".join(self._session_data.unresolved_goals[:4])
            )
        return "\n".join(parts)

    def _caller_kwargs(self, *, chat_ctx=None) -> dict[str, Any]:
        kwargs = deepcopy(self._caller_agent_kwargs)
        rag_context = dict(kwargs.get("rag_context") or {})
        handoff_context = self.handoff_context_text()
        if handoff_context:
            rag_context["current_call_state"] = handoff_context
        kwargs["rag_context"] = rag_context
        kwargs["chat_ctx"] = chat_ctx
        kwargs["session_data"] = self._session_data
        kwargs["session_router"] = self
        return kwargs

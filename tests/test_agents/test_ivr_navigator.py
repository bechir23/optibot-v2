"""Regression tests for IVR handoff behavior."""

import asyncio
from typing import Any, cast

import pytest

pytest.importorskip("livekit.agents", reason="livekit-agents dependency required for agent tests")

from app.agents.ivr_navigator import IVRNavigatorAgent
from app.agents.outbound_caller import OutboundCallerAgent


class TestIVRNavigatorHandoff:
    def test_handoff_ignores_legacy_chat_ctx_kwarg(self):
        """IVR handoff should not pass unsupported chat_ctx constructor kwargs."""
        ivr_agent = IVRNavigatorAgent(
            mutuelle="MGEN",
            caller_agent_kwargs={
                "mutuelle": "MGEN",
                "patient_name": "Jean Dupont",
                "chat_ctx": {"legacy": True},
            },
        )

        handoff_tool = cast(Any, ivr_agent.human_answered)
        handoff_agent, handoff_message = asyncio.run(handoff_tool(None))

        assert isinstance(handoff_agent, OutboundCallerAgent)
        assert "Humain detecte" in handoff_message

    def test_handoff_without_caller_kwargs(self):
        """IVR handoff should still produce a valid outbound agent with defaults."""
        ivr_agent = IVRNavigatorAgent()

        handoff_tool = cast(Any, ivr_agent.human_answered)
        handoff_agent, _ = asyncio.run(handoff_tool(None))

        assert isinstance(handoff_agent, OutboundCallerAgent)

"""Call session state — typed dataclass for LiveKit agent userdata.

Carries all mutable call state across turns, handoffs, and restarts.
Persisted to Redis via CallStateStore.checkpoint() for crash recovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallSessionState:
    """Typed session state for a single call."""

    # Identity
    call_id: str = ""
    tenant_id: str = "default"
    phone_number: str = ""
    mutuelle: str = ""

    # Patient data
    patient_name: str = ""
    patient_dob: str = ""
    nir: str = ""
    dossier_ref: str = ""
    montant: float = 0.0
    dossier_type: str = "optique"
    target_service: str = "remboursements optiques"

    # Call progress
    phase: str = "conversation"  # dialing, ivr, conversation, wrap_up, completed
    handoff_depth: int = 0
    max_handoff_depth: int = 2

    # IVR state (preserved across handoff)
    ivr_path: list[str] = field(default_factory=list)
    ivr_transcript: list[str] = field(default_factory=list)

    # Hold tracking
    hold_timeline: list[dict[str, Any]] = field(default_factory=list)

    # Extracted data (accumulates during call)
    extracted_data: dict[str, Any] = field(default_factory=dict)

    # Conversation continuity
    unresolved_goals: list[str] = field(default_factory=list)
    last_tool_name: str = ""
    last_tool_output: str = ""
    last_user_utterance: str = ""
    pending_prefixes: list[str] = field(default_factory=list)

    # Resilience counters
    llm_timeouts: int = 0
    retry_counters: dict[str, int] = field(default_factory=dict)
    durable_write_failures: int = 0

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: dict[str, Any],
        *,
        call_id: str,
        tenant_id: str,
        phone_number: str = "",
        mutuelle: str = "",
        patient_name: str = "",
        patient_dob: str = "",
        nir: str = "",
        dossier_ref: str = "",
        montant: float = 0.0,
        dossier_type: str = "optique",
        target_service: str = "remboursements optiques",
        phase: str = "conversation",
    ) -> CallSessionState:
        """Restore session state from a Redis checkpoint dict.

        Constructor args take precedence for identity fields (they come from
        dispatch metadata which is always fresh). Everything else is restored
        from the checkpoint.
        """
        return cls(
            call_id=call_id,
            tenant_id=tenant_id,
            phone_number=phone_number or str(checkpoint.get("phone_number", "") or ""),
            mutuelle=mutuelle or str(checkpoint.get("mutuelle", "") or ""),
            patient_name=patient_name,
            patient_dob=patient_dob,
            nir=nir,
            dossier_ref=dossier_ref,
            montant=montant,
            dossier_type=dossier_type,
            target_service=target_service,
            phase=str(checkpoint.get("phase", phase) or phase),
            handoff_depth=int(checkpoint.get("handoff_depth", 0) or 0),
            max_handoff_depth=int(checkpoint.get("max_handoff_depth", 2) or 2),
            ivr_path=list(checkpoint.get("ivr_path", []) or []),
            ivr_transcript=list(checkpoint.get("ivr_transcript", []) or []),
            hold_timeline=list(checkpoint.get("hold_timeline", []) or []),
            extracted_data=dict(checkpoint.get("extracted", {}) or {}),
            unresolved_goals=list(checkpoint.get("unresolved_goals", []) or []),
            last_tool_name=str(checkpoint.get("last_tool_name", "") or ""),
            last_tool_output=str(checkpoint.get("last_tool_output", "") or ""),
            last_user_utterance=str(checkpoint.get("last_user_utterance", "") or ""),
            pending_prefixes=list(checkpoint.get("pending_prefixes", []) or []),
            llm_timeouts=int(checkpoint.get("llm_timeouts", 0) or 0),
            retry_counters=dict(checkpoint.get("retry_counters", {}) or {}),
            durable_write_failures=int(checkpoint.get("durable_write_failures", 0) or 0),
        )

    def record_handoff(self) -> bool:
        """Record a handoff and return True if within limits."""
        self.handoff_depth += 1
        return self.handoff_depth <= self.max_handoff_depth

    def to_checkpoint_dict(self) -> dict[str, Any]:
        """Serialize to dict for Redis persistence."""
        return {
            "call_id": self.call_id,
            "tenant_id": self.tenant_id,
            "phone_number": self.phone_number,
            "mutuelle": self.mutuelle,
            "phase": self.phase,
            "handoff_depth": self.handoff_depth,
            "max_handoff_depth": self.max_handoff_depth,
            "ivr_path": self.ivr_path,
            "ivr_transcript": self.ivr_transcript,
            "hold_timeline": self.hold_timeline,
            "extracted": self.extracted_data,
            "unresolved_goals": self.unresolved_goals,
            "last_tool_name": self.last_tool_name,
            "last_tool_output": self.last_tool_output,
            "last_user_utterance": self.last_user_utterance,
            "pending_prefixes": self.pending_prefixes,
            "llm_timeouts": self.llm_timeouts,
            "retry_counters": self.retry_counters,
            "durable_write_failures": self.durable_write_failures,
        }

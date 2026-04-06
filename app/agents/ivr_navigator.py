"""IVR Navigator Agent — navigates mutuelle phone menus with real DTMF.

Uses LiveKit publish_dtmf() for tone sending.
Hands off to OutboundCallerAgent when human detected.
3-second cooldown between DTMF presses (LiveKit recipe).

Reference: https://docs.livekit.io/telephony/features/dtmf/
Reference: https://docs.livekit.io/recipes/ivr-navigator/
"""
from __future__ import annotations

import logging
import time
from typing import Any

from livekit.agents import Agent, RunContext, function_tool, get_job_context

from app.observability.metrics import (
    observe_ivr_latency_ms,
    record_ivr_dtmf_sent as record_ivr_dtmf,
    record_ivr_stuck,
)

logger = logging.getLogger(__name__)

DTMF_CODES = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "*": 10, "#": 11,
}


class IVRNavigatorAgent(Agent):
    """Navigates IVR menus using real DTMF + speech, then hands off."""

    def __init__(
        self,
        target_service: str = "remboursements optiques",
        max_attempts: int = 5,
        known_ivr_tree: dict | None = None,
        tenant_id: str = "default",
        mutuelle: str = "",
        caller_agent_kwargs: dict | None = None,
    ) -> None:
        hint = ""
        if known_ivr_tree:
            path = known_ivr_tree.get("path_to_reimbursement", [])
            if path:
                hint = f"\nCHEMIN CONNU: appuyer sur {' puis '.join(path)} pour atteindre le service."
            notes = known_ivr_tree.get("notes", "")
            if notes:
                hint += f"\nNOTE: {notes}"

        super().__init__(
            instructions=f"""Tu navigues dans le menu telephonique de {mutuelle}.
Ton objectif: atteindre le service "{target_service}".

REGLES:
1. Ecoute TOUTES les options du menu avant de choisir.
2. Quand tu entends l'option correspondante, appuie sur la touche avec press_digit.
3. Si tu ne comprends pas les options apres 2 ecoutes, appuie sur 0 pour un operateur.
4. Maximum {max_attempts} tentatives.
5. Des qu'un humain repond (pas un menu enregistre), appelle human_answered.
6. Si tu entends de la musique d'attente, attends sans rien faire.
7. Si c'est un repondeur, appelle voicemail_detected.
{hint}""",
        )
        self._max_attempts = max_attempts
        self._attempts = 0
        self._last_dtmf_time: float = 0
        self._tenant_id = tenant_id
        self._mutuelle = mutuelle
        self._caller_agent_kwargs = caller_agent_kwargs or {}
        self._svi_path: list[str] = []
        self._handoff_agent: Any | None = None

    @function_tool()
    async def press_digit(self, ctx: RunContext, digit: str, reason: str) -> str:
        """Press a DTMF digit to navigate the phone menu.

        Args:
            digit: The digit to press (0-9, *, #)
            reason: Why this digit (e.g. 'option 1 is for reimbursements')
        """
        if digit not in DTMF_CODES:
            return f"Invalid digit: {digit}. Use 0-9, *, or #."

        now = time.monotonic()
        if now - self._last_dtmf_time < 3.0:
            wait = 3.0 - (now - self._last_dtmf_time)
            return f"Attends {wait:.0f} secondes avant d'appuyer (cooldown)."

        self._attempts += 1
        self._svi_path.append(digit)

        # Emit IVR decision latency (time from last DTMF to this decision)
        if self._last_dtmf_time > 0:
            decision_ms = (now - self._last_dtmf_time) * 1000.0
            observe_ivr_latency_ms(decision_ms)

        self._last_dtmf_time = time.monotonic()

        record_ivr_dtmf(self._tenant_id, self._mutuelle, digit)

        try:
            job_ctx = get_job_context()
            if job_ctx and job_ctx.room and job_ctx.room.local_participant:
                await job_ctx.room.local_participant.publish_dtmf(
                    code=DTMF_CODES[digit], digit=digit
                )
                logger.info("IVR DTMF sent: %s (attempt %d/%d) — %s",
                           digit, self._attempts, self._max_attempts, reason)
        except Exception as e:
            logger.error("DTMF send failed: %s", e)
            return f"Erreur envoi touche {digit}: {e}"

        if self._attempts >= self._max_attempts:
            record_ivr_stuck(self._tenant_id, self._mutuelle)
            return "MAX_ATTEMPTS — appuie sur 0 pour un operateur."

        return f"Touche {digit} envoyee. Ecoute la suite."

    @function_tool()
    async def human_answered(self, ctx: RunContext) -> tuple:
        """A real human agent has answered. Hand off to conversation agent.

        LiveKit framework preserves chat_ctx across handoffs automatically
        (session.update_agent inserts AgentHandoff item into shared context).
        We additionally pass IVR navigation summary in rag_context so the
        conversation agent knows what path was taken.
        """
        logger.info("IVR: Human detected after path %s — handoff", self._svi_path)

        from app.agents.outbound_caller import OutboundCallerAgent

        kwargs = dict(self._caller_agent_kwargs)
        kwargs.pop("chat_ctx", None)

        # Pass IVR navigation context to conversation agent
        if "rag_context" not in kwargs:
            kwargs["rag_context"] = {}
        if self._svi_path:
            kwargs["rag_context"]["svi_path_used"] = " > ".join(self._svi_path)
        kwargs["rag_context"]["ivr_summary"] = (
            f"Navigation SVI terminee. Touches appuyees: {', '.join(self._svi_path) or 'aucune'}. "
            f"Tentatives: {self._attempts}/{self._max_attempts}. Un humain a repondu."
        )

        self._handoff_agent = OutboundCallerAgent(**kwargs)
        return self._handoff_agent, "Humain detecte, passage en mode conversation."

    @function_tool()
    async def voicemail_detected(self, ctx: RunContext) -> str:
        """Voicemail or answering machine detected. End the call."""
        logger.info("IVR: Voicemail detected for %s", self._mutuelle)
        try:
            from livekit import api
            job_ctx = get_job_context()
            if job_ctx:
                await job_ctx.api.room.delete_room(
                    api.DeleteRoomRequest(room=job_ctx.room.name)
                )
        except Exception as e:
            logger.error("Failed to hangup after voicemail: %s", e)
        return "Repondeur detecte. Appel termine."

    @function_tool()
    async def wait_for_menu(self, ctx: RunContext) -> str:
        """Wait and listen for more menu options."""
        return "En attente du menu."

    @property
    def svi_path(self) -> list[str]:
        return self._svi_path

    @property
    def handoff_agent(self) -> Any | None:
        """Returns the conversation agent created after IVR handoff, if any."""
        return self._handoff_agent

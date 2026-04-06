"""Tenant model — one optician = one tenant."""
from __future__ import annotations

from pydantic import BaseModel


class Tenant(BaseModel):
    """A tenant (optician client) in the SaaS."""

    id: str                        # "optivision-paris"
    name: str                      # "OptiVision Paris"
    phone_number: str              # Outbound caller ID
    max_concurrent_calls: int = 5
    llm_model: str = ""  # Resolved from settings at runtime if empty
    tts_voice: str = "french-female-professional"
    greeting: str = "Bonjour, je vous appelle de la part de {name} concernant un dossier de remboursement."
    ivr_target: str = "remboursements optiques"

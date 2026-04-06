"""Dossier data model — represents a patient's reimbursement case."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel


class Dossier(BaseModel):
    """A dossier (reimbursement case) to follow up on."""

    id: str
    patient_name: str
    patient_dob: date | None = None
    mutuelle: str
    mutuelle_phone: str
    dossier_type: str = ""  # "verres_progressifs", "lentilles", etc.
    bordereau_ref: str = ""
    montant: float = 0.0
    nir: str = ""  # Numéro de sécurité sociale (encrypted at rest)
    notes: str = ""
    metadata: dict[str, Any] = {}

    @property
    def display_name(self) -> str:
        """Patient name for conversation (without revealing full identity)."""
        parts = self.patient_name.split()
        if len(parts) >= 2:
            return f"M. ou Mme {parts[-1]}"
        return self.patient_name

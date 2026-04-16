"""Post-call LLM analysis pass (VAPI-style end-of-call report).

Phase 7A: After the call ends, re-read the full transcript with a
dedicated LLM pass to extract structured data + success rubric.

Why this exists:
- Live tool-extraction depends on the chat LLM remembering to call
  extract_information at the right moment. Often it forgets.
- VAPI's analysisPlan does a second async pass over the full transcript
  with a stricter schema — catches misses + grades the call.

Schema is Pydantic-validated so downstream webhook/CRM consumers get
typed fields instead of free-form dicts.

Effort: ~1 day per research agent (highest-ROI VAPI feature).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CallAnalysis(BaseModel):
    """Structured output of the post-call LLM pass.

    All fields optional — extractor returns what it finds, not None-padded.
    """
    # Core extracted data
    statut: str = Field(default="", description="en_cours|paye|rejete|en_attente|inconnu")
    motif_rejet: str = Field(default="", description="LPP_non_conforme|droits_non_ouverts|ordonnance_perimee|renouvellement_trop_tot|autre")
    delai_jours: int = Field(default=0, description="delay in business days")
    montant_paye: float = Field(default=0.0, description="amount paid in EUR")
    montant_restant: float = Field(default=0.0, description="remaining amount in EUR")
    reference_mutuelle: str = Field(default="", description="tracking reference")
    interlocuteur_nom: str = Field(default="", description="person spoken to")
    interlocuteur_service: str = Field(default="", description="department (tiers payant, remboursements, etc.)")
    code_lpp_incorrect: str = Field(default="", description="specific LPP code flagged if rejection")
    document_manquant: str = Field(default="", description="required document if missing")
    action_requise: str = Field(default="", description="resubmit|correct_and_retransmit|send_doc|wait|escalate|none")

    # Success rubric (0=no, 1=yes)
    statut_obtained: int = Field(default=0, ge=0, le=1)
    delai_obtained: int = Field(default=0, ge=0, le=1)
    interlocuteur_known: int = Field(default=0, ge=0, le=1)
    call_resolved: int = Field(default=0, ge=0, le=1, description="1 if all needed info was collected")

    # Summary for ops UI
    summary_short: str = Field(default="", description="1-sentence French summary")

    def total_score(self) -> int:
        """Sum of 4 rubric dimensions (0-4)."""
        return self.statut_obtained + self.delai_obtained + self.interlocuteur_known + self.call_resolved


ANALYSIS_PROMPT = """Tu es un analyste qualite de centre d'appels francais.
Tu viens de recevoir la transcription complete d'un appel entre un agent vocal automatique
d'un opticien et un agent de mutuelle.

Ta mission: extraire TOUTES les informations concretes echangees pendant l'appel, et juger si
les objectifs ont ete atteints.

REGLES STRICTES:
- N'invente RIEN. Si une information n'a pas ete dite, laisse le champ vide/zero.
- Les montants en euros (virgule = decimal francais): "120 euros 50" -> 120.50
- Les delais en JOURS OUVRES: "dix jours ouvres" -> 10; "deux semaines" -> 10.
- Interlocuteur: utilise seulement le prenom/nom dit explicitement (pas "l'agent").
- Action_requise: deduis la prochaine etape si possible.

REPONDS UNIQUEMENT en JSON valide respectant ce schema:
{
  "statut": "en_cours|paye|rejete|en_attente|inconnu",
  "motif_rejet": "LPP_non_conforme|droits_non_ouverts|ordonnance_perimee|renouvellement_trop_tot|autre|",
  "delai_jours": 0,
  "montant_paye": 0.0,
  "montant_restant": 0.0,
  "reference_mutuelle": "",
  "interlocuteur_nom": "",
  "interlocuteur_service": "",
  "code_lpp_incorrect": "",
  "document_manquant": "",
  "action_requise": "resubmit|correct_and_retransmit|send_doc|wait|escalate|none",
  "statut_obtained": 0,
  "delai_obtained": 0,
  "interlocuteur_known": 0,
  "call_resolved": 0,
  "summary_short": "1 phrase en francais resumant l'issue de l'appel"
}
"""


async def analyze_call(transcript: list[dict[str, Any]], llm_model: str = "openai/gpt-4.1-mini") -> CallAnalysis:
    """Run post-call LLM analysis on a full transcript.

    Args:
        transcript: list of {role: agent|user|simulator, text: str} dicts
        llm_model: model to use (default gpt-4.1-mini, slow/reasoner model recommended)

    Returns:
        CallAnalysis with extracted fields + success rubric.
        On failure, returns a CallAnalysis with all defaults (don't raise — non-critical).
    """
    if not transcript:
        return CallAnalysis()

    # Format transcript for the LLM
    lines = []
    for turn in transcript:
        role = turn.get("role") or turn.get("speaker") or "?"
        text = turn.get("text", "")
        if role == "system":
            continue
        # Map simulator -> mutuelle_agent for clarity
        role_label = {
            "agent": "OPTICIEN_AGENT",
            "assistant": "OPTICIEN_AGENT",
            "user": "MUTUELLE_AGENT",
            "simulator": "MUTUELLE_AGENT",
        }.get(role, role.upper())
        lines.append(f"[{role_label}] {text}")

    transcript_text = "\n".join(lines)
    if not transcript_text.strip():
        return CallAnalysis()

    try:
        import os
        from openai import AsyncOpenAI

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.debug("No OPENAI_API_KEY — skipping post-call analysis")
            return CallAnalysis()

        client = AsyncOpenAI(api_key=api_key)
        model_name = llm_model.replace("openai/", "")

        resp = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": ANALYSIS_PROMPT},
                {"role": "user", "content": f"TRANSCRIPTION:\n\n{transcript_text}"},
            ],
            max_tokens=800,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        return CallAnalysis(**data)

    except Exception as e:
        logger.warning("Post-call analysis failed (non-critical): %s", e)
        return CallAnalysis()

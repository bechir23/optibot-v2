"""Dynamic Deepgram keyterm builder — per-call vocabulary selection.

Deepgram Nova-3 limits: 100 keyterms, 500 tokens per request.
Strategy: base_terms (always) + mutuelle-specific + optical + call-relevant.
Terms are loaded from JSON, refreshable at runtime via ConfigRegistry.

Production voice agents need domain-specific vocabulary:
- 50+ mutuelles (Harmonie, MGEN, AG2R, Malakoff, AXA, ...)
- 20+ optical terms (verres progressifs, monture, lentilles, ...)
- 20+ insurance terms (tiers payant, bordereau, FINESS, NIR, ...)
- 10+ platform names (Almerys, Viamedis, Santéclair, ...)
- Call-specific: the target mutuelle name + common misheard variants
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_KEYTERMS_PATH = Path(__file__).resolve().parents[2] / "data" / "deepgram_keyterms.json"
_MAX_KEYTERMS = 100
_MAX_TOKENS = 500  # Deepgram limit


def _estimate_tokens(terms: list[str]) -> int:
    """Rough token estimate: ~1.3 tokens per word for French."""
    return sum(max(1, int(len(t.split()) * 1.3)) for t in terms)


def _load_keyterm_db() -> dict:
    """Load the keyterm database from JSON."""
    path_override = os.getenv("OPTIBOT_KEYTERMS_PATH")
    path = Path(path_override) if path_override else _DEFAULT_KEYTERMS_PATH

    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load keyterms from %s: %s", path, e)

    return {}


_KEYTERM_DB = _load_keyterm_db()


def build_keyterms(
    mutuelle: str = "",
    dossier_type: str = "optique",
    extra_terms: list[str] | None = None,
) -> list[str]:
    """Build a per-call keyterm list optimized for Deepgram Nova-3.

    Priority order (filled until 100 terms / 500 tokens):
    1. base_terms (core insurance/optician vocabulary)
    2. The specific mutuelle name for this call
    3. optical_terms (if dossier_type is optique)
    4. insurance_terms
    5. teletransmission_platforms
    6. call_flow_terms
    7. Extra terms (from caller metadata)
    8. Top mutuelles (fill remaining slots)

    Returns: list of max 100 keyterms.
    """
    db = _KEYTERM_DB
    selected: list[str] = []
    seen: set[str] = set()

    def _add(terms: list[str]) -> None:
        for t in terms:
            t_clean = t.strip()
            if not t_clean or t_clean.lower() in seen:
                continue
            if len(selected) >= _MAX_KEYTERMS:
                return
            if _estimate_tokens(selected + [t_clean]) > _MAX_TOKENS:
                return
            seen.add(t_clean.lower())
            selected.append(t_clean)

    # 1. Base terms (always)
    base = db.get("base_terms", {}).get("terms", [])
    _add(base)

    # 2. The specific mutuelle for this call
    if mutuelle:
        _add([mutuelle])
        # Also add known aliases for this mutuelle from STT correction data
        try:
            alias_path = Path(__file__).resolve().parents[2] / "data" / "stt_mutuelle_aliases.json"
            if alias_path.exists():
                aliases = json.loads(alias_path.read_text(encoding="utf-8"))
                if isinstance(aliases, dict) and mutuelle in aliases:
                    _add(aliases[mutuelle][:5])  # Max 5 aliases per mutuelle
        except (OSError, json.JSONDecodeError):
            pass

    # 3. Optical terms (if relevant)
    if dossier_type in ("optique", ""):
        optical = db.get("optical_terms", {}).get("terms", [])
        _add(optical)

    # 4. Insurance terms
    insurance = db.get("insurance_terms", {}).get("terms", [])
    _add(insurance)

    # 5. Platform names
    platforms = db.get("teletransmission_platforms", {}).get("terms", [])
    _add(platforms)

    # 6. Call flow terms
    flow = db.get("call_flow_terms", {}).get("terms", [])
    _add(flow)

    # 7. Extra terms from caller metadata
    if extra_terms:
        _add(extra_terms)

    # 8. Fill with top mutuelles
    top = db.get("mutuelles_top50", {}).get("terms", [])
    _add(top)

    logger.debug("Built %d keyterms (%d estimated tokens) for %s/%s",
                len(selected), _estimate_tokens(selected), mutuelle, dossier_type)
    return selected


def reload_keyterm_db() -> None:
    """Reload the keyterm database from file (called by ConfigRegistry)."""
    global _KEYTERM_DB
    _KEYTERM_DB = _load_keyterm_db()

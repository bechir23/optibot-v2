"""Fuzzy mutuelle name matching — handles unknown STT variants.

Uses RapidFuzz for fuzzy string matching when deterministic STT correction
doesn't match. Falls back gracefully if RapidFuzz not installed.

Example: "armoni mutuel" (not in correction list) → "Harmonie Mutuelle" (score 82%)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_KNOWN_MUTUELLES_ENV = "OPTIBOT_KNOWN_MUTUELLES_PATH"
_MUTUELLE_ALIASES_ENV = "OPTIBOT_MUTUELLE_ALIASES_PATH"
_DEFAULT_KNOWN_MUTUELLES_PATH = Path(__file__).resolve().parents[2] / "data" / "known_mutuelles.json"
_DEFAULT_MUTUELLE_ALIASES_PATH = Path(__file__).resolve().parents[2] / "data" / "stt_mutuelle_aliases.json"

_FALLBACK_KNOWN_MUTUELLES = [
    "Harmonie Mutuelle", "MGEN", "AG2R La Mondiale", "Malakoff Humanis",
    "Almerys", "Viamedis", "Swiss Life", "AXA", "Generali",
    "MAAF", "MMA", "Macif", "MAIF", "GMF", "Pro BTP",
    "Ipselia", "Groupama", "Mutuelle Generale", "MGEFI", "LMDE",
    "SMEREP", "SMENO", "SMERRA", "Alan", "April",
]


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _load_names_list(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []

    names: list[str] = []
    for item in payload:
        if isinstance(item, str):
            names.append(item)
    return names


def _load_alias_canonicals(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []

    names: list[str] = []
    for canonical in payload.keys():
        if isinstance(canonical, str):
            names.append(canonical)
    return names


def _build_known_mutuelles() -> list[str]:
    names = list(_FALLBACK_KNOWN_MUTUELLES)

    known_override = os.getenv(_KNOWN_MUTUELLES_ENV)
    if known_override:
        names.extend(_load_names_list(Path(known_override)))

    alias_override = os.getenv(_MUTUELLE_ALIASES_ENV)
    if alias_override:
        names.extend(_load_alias_canonicals(Path(alias_override)))

    names.extend(_load_names_list(_DEFAULT_KNOWN_MUTUELLES_PATH))
    names.extend(_load_alias_canonicals(_DEFAULT_MUTUELLE_ALIASES_PATH))

    return _dedupe_keep_order(names)


KNOWN_MUTUELLES = _build_known_mutuelles()

# ── Dynamic registry hook ────────────────────────────────────────────
_runtime_known_mutuelles: list[str] | None = None
_runtime_mutuelles_version: int = 0


def set_runtime_known_mutuelles(mutuelles: list[str], version: int) -> None:
    """Called by ConfigRegistry to push updated mutuelle list."""
    global _runtime_known_mutuelles, _runtime_mutuelles_version, KNOWN_MUTUELLES
    if version <= _runtime_mutuelles_version:
        return
    _runtime_known_mutuelles = mutuelles
    _runtime_mutuelles_version = version
    KNOWN_MUTUELLES = _dedupe_keep_order(mutuelles)


_rapidfuzz_available = False
try:
    from rapidfuzz import process, fuzz, utils
    _rapidfuzz_available = True
except ImportError:
    logger.info("RapidFuzz not installed — fuzzy matching disabled")


def match_mutuelle(name: str, score_cutoff: float = 70.0, extra_choices: list[str] | None = None) -> str | None:
    """Try to match an unknown mutuelle name to a known one.

    Returns the matched name if confidence >= score_cutoff, else None.
    """
    if not _rapidfuzz_available or not name:
        return None

    choices = list(KNOWN_MUTUELLES)
    if extra_choices:
        choices.extend(extra_choices)

    result = process.extractOne(
        name.strip(),
        choices,
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        score_cutoff=score_cutoff,
    )

    if result:
        matched_name, score, idx = result
        logger.info("Fuzzy match: '%s' → '%s' (score=%.1f%%)", name, matched_name, score)
        return matched_name

    return None

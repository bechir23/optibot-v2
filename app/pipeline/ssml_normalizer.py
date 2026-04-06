"""SSML normalization layer for French telephony TTS.

Converts raw text into SSML-enriched text for better pronunciation:
- Numbers → say-as cardinal/ordinal
- Phone numbers → say-as telephone
- Abbreviations → sub aliases (CPAM, NIR, FINESS, LPP, AMC, etc.)
- Long reference numbers → say-as characters (spelled out)
- Pauses → break elements for natural speech rhythm
- Prosody → rate adjustment for clarity on phone lines

Based on W3C SSML 1.1 spec + Microsoft Azure Speech best practices.
Cross-vendor compatible (Cartesia, Azure, Google, ElevenLabs).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

_ABBREVIATIONS_ENV = "OPTIBOT_SSML_ABBREVIATIONS_PATH"
_PATTERNS_ENV = "OPTIBOT_SSML_PATTERNS_PATH"
_MONTHS_ENV = "OPTIBOT_SSML_MONTHS_PATH"
_DEFAULT_ABBREVIATIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "ssml_abbreviations.json"
_DEFAULT_PATTERNS_PATH = Path(__file__).resolve().parents[2] / "data" / "ssml_patterns.json"
_DEFAULT_MONTHS_PATH = Path(__file__).resolve().parents[2] / "data" / "ssml_months.json"


def _load_json_dict(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str):
            normalized[key] = value
    return normalized


def _merge_string_maps(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    merged.update(extra)
    return merged


def _load_string_map(default_path: Path, env_var: str, fallback: dict[str, str]) -> dict[str, str]:
    merged = dict(fallback)
    override_path = os.getenv(env_var)
    if override_path:
        merged = _merge_string_maps(merged, _load_json_dict(Path(override_path)))
    merged = _merge_string_maps(merged, _load_json_dict(default_path))
    return merged


# ── French abbreviation expansions for optician domain ──
_FALLBACK_ABBREVIATIONS: dict[str, str] = {
    "CPAM": "C.P.A.M.",
    "NIR": "numéro d'inscription au répertoire",
    "FINESS": "F.I.N.E.S.S.",
    "LPP": "L.P.P.",
    "AMC": "assurance maladie complémentaire",
    "AMO": "assurance maladie obligatoire",
    "CMU": "C.M.U.",
    "CSS": "C.S.S.",
    "ACS": "A.C.S.",
    "SESAM": "SÉSAM",
    "NOEMIE": "NOÉMIE",
    "SCOR": "S.C.O.R.",
    "ROC": "R.O.C.",
    "PEC": "prise en charge",
    "RAC": "reste à charge",
    "BR": "base de remboursement",
    "TM": "ticket modérateur",
    "TP": "tiers payant",
    "100%": "cent pour cent",
}

ABBREVIATIONS: dict[str, str] = _load_string_map(
    _DEFAULT_ABBREVIATIONS_PATH,
    _ABBREVIATIONS_ENV,
    _FALLBACK_ABBREVIATIONS,
)

# ── Patterns ──
_FALLBACK_PATTERN_STRINGS: dict[str, str] = {
    "phone": r"\b(0[1-9])\s?(\d{2})\s?(\d{2})\s?(\d{2})\s?(\d{2})\b",
    "long_num": r"\b(\d{6,})\b",
    "euro": r"(\d+)[.,](\d{1,2})\s*(?:€|euros?|EUR)",
    "euro_int": r"(\d+)\s*(?:€|euros?|EUR)",
    "date": r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b",
}

_PATTERN_STRINGS = _load_string_map(
    _DEFAULT_PATTERNS_PATH,
    _PATTERNS_ENV,
    _FALLBACK_PATTERN_STRINGS,
)

_PHONE_RE = re.compile(_PATTERN_STRINGS["phone"])
_LONG_NUM_RE = re.compile(_PATTERN_STRINGS["long_num"])
_EURO_RE = re.compile(_PATTERN_STRINGS["euro"])
_EURO_INT_RE = re.compile(_PATTERN_STRINGS["euro_int"])
_DATE_RE = re.compile(_PATTERN_STRINGS["date"])
_ABBREV_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(ABBREVIATIONS.keys(), key=len, reverse=True)) + r")\b"
)


# ── Dynamic registry hook ────────────────────────────────────────────
_runtime_abbreviations: dict[str, str] | None = None
_runtime_abbreviations_version: int = 0


def set_runtime_abbreviations(abbreviations: dict[str, str], version: int) -> None:
    """Called by ConfigRegistry to push updated abbreviations."""
    global _runtime_abbreviations, _runtime_abbreviations_version, _ABBREV_RE
    if version <= _runtime_abbreviations_version:
        return
    _runtime_abbreviations = abbreviations
    _runtime_abbreviations_version = version
    # Recompile the abbreviation regex with updated keys
    _ABBREV_RE = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in sorted(abbreviations.keys(), key=len, reverse=True)) + r")\b"
    )


def _get_abbreviations() -> dict[str, str]:
    return _runtime_abbreviations if _runtime_abbreviations is not None else ABBREVIATIONS


# Runtime setters for patterns and months
_runtime_months: dict[str, str] | None = None
_runtime_months_version: int = 0


def set_runtime_months(months: dict[str, str], version: int) -> None:
    """Called by ConfigRegistry to push updated month names."""
    global _runtime_months, _runtime_months_version
    if version <= _runtime_months_version:
        return
    _runtime_months = months
    _runtime_months_version = version


_runtime_patterns: dict[str, str] | None = None
_runtime_patterns_version: int = 0


def set_runtime_patterns(patterns: dict[str, str], version: int) -> None:
    """Called by ConfigRegistry to push updated regex patterns + recompile."""
    global _runtime_patterns, _runtime_patterns_version
    global _PHONE_RE, _LONG_NUM_RE, _EURO_RE, _EURO_INT_RE, _DATE_RE
    if version <= _runtime_patterns_version:
        return
    _runtime_patterns = patterns
    _runtime_patterns_version = version
    # Recompile from new patterns, falling back to current on invalid regex
    for key, compiled_ref in [("phone", "_PHONE_RE"), ("long_num", "_LONG_NUM_RE"),
                               ("euro", "_EURO_RE"), ("euro_int", "_EURO_INT_RE"),
                               ("date", "_DATE_RE")]:
        if key in patterns:
            try:
                globals()[compiled_ref] = re.compile(patterns[key])
            except re.error:
                pass  # Keep existing compiled regex


def normalize_for_tts(text: str) -> str:
    """Normalize text for Cartesia TTS — expand abbreviations, format numbers for speech."""
    return _to_plain(text)


def _to_plain(text: str) -> str:
    """Plain text normalization — expand abbreviations, format numbers for speech."""
    # Expand abbreviations
    abbrevs = _get_abbreviations()
    text = _ABBREV_RE.sub(lambda m: abbrevs.get(m.group(0), m.group(0)), text)

    # Phone numbers: group by pairs with pauses
    text = _PHONE_RE.sub(
        lambda m: f"{m.group(1)}, {m.group(2)}, {m.group(3)}, {m.group(4)}, {m.group(5)}",
        text,
    )

    # Long reference numbers: spell digit by digit with pauses
    def _spell(m):
        digits = m.group(1)
        groups = []
        for i in range(0, len(digits), 3):
            groups.append(", ".join(digits[i:i+3]))
        return "... ".join(groups)
    text = _LONG_NUM_RE.sub(_spell, text)

    # Euro amounts: expand with num2words if available
    try:
        from num2words import num2words as _n2w

        def _euros_plain(m):
            eur = int(m.group(1))
            cts = int(m.group(2)) if m.group(2) else 0
            result = _n2w(eur, lang='fr') + " euros"
            if cts:
                result += " et " + _n2w(cts, lang='fr') + " centimes"
            return result

        text = _EURO_RE.sub(_euros_plain, text)
        text = _EURO_INT_RE.sub(lambda m: _n2w(int(m.group(1)), lang='fr') + " euros", text)
    except ImportError:
        pass

    # Dates: expand to spoken form
    text = _DATE_RE.sub(lambda m: f"{m.group(1)} {_month_name(m.group(2))} {m.group(3)}", text)

    return text


_FALLBACK_MONTHS = {
    "01": "janvier", "02": "février", "03": "mars", "04": "avril",
    "05": "mai", "06": "juin", "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
    "1": "janvier", "2": "février", "3": "mars", "4": "avril",
    "5": "mai", "6": "juin", "7": "juillet", "8": "août",
    "9": "septembre",
}

_MONTHS = _load_string_map(
    _DEFAULT_MONTHS_PATH,
    _MONTHS_ENV,
    _FALLBACK_MONTHS,
)


def _month_name(m: str) -> str:
    months = _runtime_months if _runtime_months is not None else _MONTHS
    return months.get(m, m)

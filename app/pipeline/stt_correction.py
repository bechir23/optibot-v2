"""Post-STT correction for French mutuelle names, optician terms, and emails.

KEPT from OptiBot v1 (tools/stt_correction.py).
CHANGED: Removed Pipecat FrameProcessor dependency — now a standalone function.
The LiveKit agent calls correct_transcription() directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re


_MUTUELLE_ALIASES_ENV = "OPTIBOT_MUTUELLE_ALIASES_PATH"
_TERM_ALIASES_ENV = "OPTIBOT_TERM_ALIASES_PATH"
_DEFAULT_MUTUELLE_ALIASES_PATH = Path(__file__).resolve().parents[2] / "data" / "stt_mutuelle_aliases.json"
_DEFAULT_TERM_ALIASES_PATH = Path(__file__).resolve().parents[2] / "data" / "stt_term_aliases.json"

_ALIAS_SEPARATOR_PATTERN = r"[\s\.\-_'’%]*"
_ACCENTED_CHAR_GROUPS = {
    "a": "[aàáâä]",
    "c": "[cç]",
    "e": "[eéèêë]",
    "i": "[iíìîï]",
    "o": "[oóòôö]",
    "u": "[uúùûü]",
    "y": "[yÿ]",
}


# Fallback aliases are intentionally concise.
# Production/custom aliases are loaded dynamically from data/*.json.
_FALLBACK_MUTUELLE_ALIASES: dict[str, list[str]] = {
    "Harmonie Mutuelle": ["armoni mutuel", "harmoni mutuel", "armonie mutuel", "armonimutuel"],
    "MGEN": ["em g e n", "emgen", "mgene", "m jen", "m g e n"],
    "AG2R": ["a g 2 r", "ag deux r", "agdeur", "ag to air"],
    "La Mondiale": ["la mondial"],
    "Malakoff": ["malacof", "malakof"],
    "Humanis": ["umani"],
    "Almerys": ["almeris", "almeri", "ammerys", "ammeris", "almerisse"],
    "Viamedis": ["via medis", "via medi", "via medicelium", "via medic", "vias medis"],
    "Swiss Life": ["suisse life", "swift life"],
    "AXA": ["axa"],
    "Generali": ["jenerali"],
    "MAAF": ["maaf", "m a a f"],
    "MMA": ["m m a"],
    "Macif": ["massif", "macif"],
    "MAIF": ["maif", "m a i f"],
    "GMF": ["g m f"],
    "Pro BTP": ["pro btp", "pro b t p"],
    "Ipselia": ["ipselia"],
    "Groupama": ["groupama", "groupa", "groupama mutuel", "groupamac mutuel", "groupamac"],
    "Mutuelle Generale": ["mutuel general"],
    "MGEFI": ["m g e f i", "mgefi"],
    "LMDE": ["l m d e"],
    "SMEREP": ["smerep"],
    "SMENO": ["smeno"],
    "SMERRA": ["smerra"],
}

_FALLBACK_TERM_ALIASES: dict[str, list[str]] = {
    "LPP": ["el pe pe", "el p p", "elpepe"],
    "teletransmission": ["telepransmission", "tele transmission", "teletransmision"],
    "SESAM-Vitale": ["sezam vital", "sesam vitale", "sesam vital", "s e s a m v ital"],
    "AMC": ["a m c"],
    "AMO": ["a m o"],
    "FINESS": ["finess", "f i n e s s"],
    "CPAM": ["c p a m"],
    "NIR": ["n i r", "nar", "henneard", "hennéard"],
    "tiers payant": ["tier payant", "tiers paillant"],
    "100% Sante": ["cent pour cent sante", "sanpoursan sante", "100 sante"],
    "entente prealable": ["antente prealable"],
    "bordereau": ["bord d euro", "bord d oraux", "bord d eau", "bordreau", "bordr eau"],
    "verres progressifs": ["vert progressif", "vers progressif", "ver progressifs"],
}


def _normalize_alias_list(raw_aliases: object) -> list[str]:
    if not isinstance(raw_aliases, list):
        return []

    aliases: list[str] = []
    for alias in raw_aliases:
        if not isinstance(alias, str):
            continue
        normalized = " ".join(alias.split())
        if normalized:
            aliases.append(normalized)
    return aliases


def _load_alias_file(path: Path) -> dict[str, list[str]]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    alias_map: dict[str, list[str]] = {}
    for canonical, aliases in payload.items():
        if not isinstance(canonical, str):
            continue
        normalized_canonical = " ".join(canonical.split())
        if not normalized_canonical:
            continue
        normalized_aliases = _normalize_alias_list(aliases)
        if normalized_aliases:
            alias_map[normalized_canonical] = normalized_aliases
    return alias_map


def _merge_aliases(base: dict[str, list[str]], extra: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {canonical: list(aliases) for canonical, aliases in base.items()}

    for canonical, aliases in extra.items():
        if canonical not in merged:
            merged[canonical] = []
        for alias in aliases:
            if alias not in merged[canonical]:
                merged[canonical].append(alias)
    return merged


def _load_alias_map(
    fallback_aliases: dict[str, list[str]],
    default_path: Path,
    env_var: str,
) -> dict[str, list[str]]:
    alias_map = {canonical: list(aliases) for canonical, aliases in fallback_aliases.items()}

    override_path = os.getenv(env_var)
    if override_path:
        alias_map = _merge_aliases(alias_map, _load_alias_file(Path(override_path)))

    alias_map = _merge_aliases(alias_map, _load_alias_file(default_path))
    return alias_map


def _token_to_pattern(token: str) -> str:
    chunks: list[str] = []
    for char in token.lower():
        chunks.append(_ACCENTED_CHAR_GROUPS.get(char, re.escape(char)))
    return "".join(chunks)


def _compile_alias_regex(alias: str) -> re.Pattern[str] | None:
    tokens = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", alias)
    if not tokens:
        return None

    token_patterns = [_token_to_pattern(token) for token in tokens]
    pattern = rf"\b{_ALIAS_SEPARATOR_PATTERN.join(token_patterns)}\b"
    return re.compile(pattern, re.IGNORECASE)


def _compile_alias_corrections(alias_map: dict[str, list[str]]) -> list[tuple[re.Pattern[str], str]]:
    compiled: list[tuple[re.Pattern[str], str]] = []
    seen: set[tuple[str, str]] = set()
    entries: list[tuple[str, str]] = []

    for canonical, aliases in alias_map.items():
        canonical_norm = " ".join(canonical.split())
        entries.append((canonical_norm, canonical_norm))
        for alias in aliases:
            alias_norm = " ".join(alias.split())
            if alias_norm:
                entries.append((alias_norm, canonical_norm))

    # Apply longer aliases first to avoid replacing short prefixes too early.
    entries.sort(key=lambda item: len(item[0]), reverse=True)

    for alias, canonical in entries:
        regex = _compile_alias_regex(alias)
        if regex is None:
            continue
        key = (regex.pattern, canonical)
        if key in seen:
            continue
        seen.add(key)
        compiled.append((regex, canonical))

    return compiled


# ── Mutuelle name corrections ─────────────────────────────────────────

_MUTUELLE_ALIASES = _load_alias_map(
    _FALLBACK_MUTUELLE_ALIASES,
    _DEFAULT_MUTUELLE_ALIASES_PATH,
    _MUTUELLE_ALIASES_ENV,
)
_MUTUELLE_COMPILED = _compile_alias_corrections(_MUTUELLE_ALIASES)
_KNOWN_MUTUELLE_NAMES = set(_MUTUELLE_ALIASES.keys())

_INSURANCE_CONTEXT = r"(?:mutuelle|assurance|complementaire|compl[eé]mentaire|sante|sant[eé])"
_CONTEXTUAL_MUTUELLES = [
    (re.compile(rf"(?:chez\s+)avril\b|\bavril\s+{_INSURANCE_CONTEXT}", re.IGNORECASE), "April"),
    (re.compile(rf"{_INSURANCE_CONTEXT}\s+avril\b", re.IGNORECASE),
     lambda m: m.group(0).replace("avril", "April").replace("Avril", "April")),
    (re.compile(rf"(?:chez\s+)alan\b|\balan\s+{_INSURANCE_CONTEXT}", re.IGNORECASE), "Alan"),
    (re.compile(rf"{_INSURANCE_CONTEXT}\s+alan\b", re.IGNORECASE),
     lambda m: m.group(0).replace("alan", "Alan")),
]


# ── Optician / insurance terms ─────────────────────────────────────────

_TERM_ALIASES = _load_alias_map(
    _FALLBACK_TERM_ALIASES,
    _DEFAULT_TERM_ALIASES_PATH,
    _TERM_ALIASES_ENV,
)
_TERM_COMPILED = _compile_alias_corrections(_TERM_ALIASES)


# ── Email patterns (structural, not business-domain) ────────────────────

_AROBASE_RE = re.compile(r"\s*(arobase|arrobase|arobas)\s*", re.IGNORECASE)
_AT_STANDALONE_RE = re.compile(r"\s+at\s+", re.IGNORECASE)
_POINT_DOMAIN_RE = re.compile(r"\s*point\s+(com|fr|net|org|ch|be|de|eu|io)\b", re.IGNORECASE)
_POINT_RE = re.compile(r"(\w)\s+point\s+(\w)", re.IGNORECASE)

# Domain corrections — data-driven via JSON or env, with fallback
_DEFAULT_DOMAIN_CORRECTIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "stt_domain_corrections.json"
_FALLBACK_DOMAIN_CORRECTIONS = {
    r"\bg\s*mail\b": "gmail",
    r"\bhot\s*mail\b": "hotmail",
    r"\bout\s*look\b": "outlook",
    r"\bya\s*hoo\b": "yahoo",
    r"\bla\s*poste\b": "laposte",
    r"\bwana\s*doo\b": "wanadoo",
}


def _load_domain_corrections() -> list[tuple[re.Pattern[str], str]]:
    """Load domain corrections from file, env, or fallback."""
    raw = dict(_FALLBACK_DOMAIN_CORRECTIONS)
    override = os.getenv("OPTIBOT_DOMAIN_CORRECTIONS_PATH")
    if override:
        try:
            data = json.loads(Path(override).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw.update(data)
        except (OSError, json.JSONDecodeError):
            pass
    if _DEFAULT_DOMAIN_CORRECTIONS_PATH.exists():
        try:
            data = json.loads(_DEFAULT_DOMAIN_CORRECTIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw.update(data)
        except (OSError, json.JSONDecodeError):
            pass
    compiled = []
    for pattern, replacement in raw.items():
        try:
            compiled.append((re.compile(pattern, re.IGNORECASE), replacement))
        except re.error:
            pass  # Skip invalid patterns
    return compiled


_DOMAIN_COMPILED = _load_domain_corrections()

# French phonetic alphabet
_COMME_RE = re.compile(r"\b([a-zA-Z])\s+comme\s+\w+", re.IGNORECASE)


# ── Dynamic registry hook ────────────────────────────────────────────
# When ConfigRegistry is active, it can push updated aliases here.
# This avoids importing config_registry at module level (circular import).
_runtime_mutuelle_compiled: list[tuple[re.Pattern[str], str]] | None = None
_runtime_aliases_version: int = 0


def set_runtime_aliases(aliases: dict[str, list[str]], version: int) -> None:
    """Called by ConfigRegistry to push updated aliases into the correction pipeline."""
    global _runtime_mutuelle_compiled, _runtime_aliases_version
    if version <= _runtime_aliases_version:
        return
    _runtime_mutuelle_compiled = _compile_alias_corrections(aliases)
    _runtime_aliases_version = version


def correct_transcription(text: str) -> str:
    """Apply all STT corrections to a transcription.

    Order matters:
    1. Mutuelle names (most impactful) — uses runtime aliases if available
    2. Optician/insurance terms
    3. Email patterns
    4. French phonetic alphabet
    """
    result = text

    # Mutuelle names — prefer runtime-refreshed aliases over startup-loaded
    corrections = _runtime_mutuelle_compiled if _runtime_mutuelle_compiled is not None else _MUTUELLE_COMPILED
    for pattern, replacement in corrections:
        result = pattern.sub(replacement, result)
    for pattern, replacement in _CONTEXTUAL_MUTUELLES:
        if callable(replacement):
            result = pattern.sub(replacement, result)
        else:
            result = pattern.sub(replacement, result)

    # Optician terms
    for pattern, replacement in _TERM_COMPILED:
        result = pattern.sub(replacement, result)

    # Email corrections
    result = _AROBASE_RE.sub("@", result)
    result = _AT_STANDALONE_RE.sub("@", result)
    result = _POINT_DOMAIN_RE.sub(lambda m: f".{m.group(1).lower()}", result)
    result = _POINT_RE.sub(r"\1.\2", result)
    for compiled_re, replacement in _DOMAIN_COMPILED:
        result = compiled_re.sub(replacement, result)

    # Spelling collapse
    result = _COMME_RE.sub(lambda m: m.group(1).upper(), result)

    # Fuzzy mutuelle name matching as fallback for unknown variants.
    # Skip if a known mutuelle name is already present (avoids double-replacement).
    try:
        from app.pipeline.fuzzy_matching import match_mutuelle, KNOWN_MUTUELLES
        known_names = _KNOWN_MUTUELLE_NAMES.union(KNOWN_MUTUELLES)
        already_has_known = any(km.lower() in result.lower() for km in known_names)
        if not already_has_known:
            words = result.split()
            for length in (3, 2):
                for i in range(len(words) - length + 1):
                    candidate = " ".join(words[i:i+length])
                    if len(candidate) < 5:
                        continue
                    matched = match_mutuelle(candidate, score_cutoff=82.0)
                    if matched and matched.lower() != candidate.lower():
                        result = result.replace(candidate, matched, 1)
                        break
                else:
                    continue
                break
    except ImportError:
        pass

    return result

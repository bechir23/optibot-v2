"""Hold Music Detector — two-tier confidence system.

Two-tier detection:
  - Tier 1 (HIGH): IVR/system phrases → instant hold (1 match)
  - Tier 2 (LOW): Ambiguous phrases → hold after 2 matches in 8s window
  - Agent working phrases ("je vérifie") cancel ambiguous signals

Phrase lists are data-driven: loaded from JSON files, overridable via env vars.
Fallback to hardcoded minimums only if no file found.
"""
from __future__ import annotations

import json
import logging
import os
import time
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _load_phrase_list(filename: str, env_var: str, fallback: list[str]) -> list[str]:
    """Load phrase list from JSON file, env override, or fallback."""
    result = list(fallback)
    # Env override
    override = os.getenv(env_var)
    if override:
        try:
            data = json.loads(Path(override).read_text(encoding="utf-8"))
            if isinstance(data, list):
                result = [s for s in data if isinstance(s, str)]
                return result
        except (OSError, json.JSONDecodeError):
            pass
    # Default file
    path = _DATA_DIR / filename
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                result = [s for s in data if isinstance(s, str)]
                return result
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _normalize_match_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


# ── Tier 1: System/IVR hold phrases — NEVER said by a human agent ────
HOLD_SYSTEM_PHRASES = _load_phrase_list(
    "hold_system_phrases.json",
    "OPTIBOT_HOLD_SYSTEM_PHRASES_PATH",
    [
        "veuillez patienter", "merci de patienter", "merci de rester en ligne",
        "votre appel est important", "temps d'attente", "un conseiller va prendre",
        "vous êtes en position", "nous allons prendre votre appel",
        "patientez quelques instants", "veuillez rester en ligne",
        "nous vous remercions de votre patience", "please hold", "please wait",
        "votre temps d'attente estimé", "toutes nos lignes sont occupées",
    ],
)

# ── Tier 2: Ambiguous phrases — agents also say these ─────────────────
HOLD_AMBIGUOUS_PHRASES = _load_phrase_list(
    "hold_ambiguous_phrases.json",
    "OPTIBOT_HOLD_AMBIGUOUS_PHRASES_PATH",
    ["attendez", "un instant", "un moment", "ne quittez pas", "deux minutes", "en attente"],
)

# ── Human return phrases ─────────────────────────────────────────────
HUMAN_PHRASES = _load_phrase_list(
    "hold_human_phrases.json",
    "OPTIBOT_HOLD_HUMAN_PHRASES_PATH",
    [
        "bonjour", "allô", "allo", "comment puis-je vous aider", "service",
        "je vous écoute", "en quoi puis-je", "qui est à l'appareil",
        "c'est à quel sujet", "oui bonjour", "que puis-je faire",
        "j'ai votre dossier", "je reviens", "c'est bon", "alors", "donc", "voilà",
    ],
)

# ── Agent working phrases — cancel ambiguous hold signals ────────────
AGENT_WORKING_PHRASES = _load_phrase_list(
    "hold_agent_working_phrases.json",
    "OPTIBOT_HOLD_AGENT_WORKING_PATH",
    ["je vérifie", "je cherche", "je regarde", "laissez-moi", "je vais voir", "je consulte"],
)


class HoldDetector:
    """Standalone hold music detector. No framework dependency.

    Usage:
        detector = HoldDetector()
        result = detector.detect("veuillez patienter")
        if result.is_hold:
            # suppress transcription, bot stays silent
        elif result.hold_ended:
            # human is back, resume conversation
    """

    def __init__(
        self,
        hold_timeout_secs: float = 1200.0,
        ambiguous_window_secs: float = 8.0,
        ambiguous_threshold: int = 2,
    ):
        self._on_hold = False
        self._hold_start: float = 0
        self._hold_duration: float = 0
        self._hold_timeout = hold_timeout_secs
        self._ambiguous_window = ambiguous_window_secs
        self._ambiguous_threshold = ambiguous_threshold
        self._ambiguous_hits: list[float] = []

    @property
    def on_hold(self) -> bool:
        return self._on_hold

    @property
    def hold_duration(self) -> float:
        if self._on_hold:
            return time.monotonic() - self._hold_start
        return self._hold_duration

    def detect(self, text: str) -> HoldResult:
        """Process a transcription and return hold detection result.

        Returns HoldResult with:
          - is_hold: True if text is hold music (should be suppressed)
          - hold_started: True if this text triggered hold mode
          - hold_ended: True if human voice detected after hold
          - hold_timeout: True if max hold duration exceeded
        """
        text_lower = _normalize_match_text(text)
        if not text_lower:
            return HoldResult(is_hold=self._on_hold)

        if not self._on_hold:
            return self._detect_not_on_hold(text_lower, text)
        else:
            return self._detect_on_hold(text_lower, text)

    def _detect_not_on_hold(self, text_lower: str, original: str) -> HoldResult:
        # Tier 1: System hold → instant trigger
        if any(_normalize_match_text(phrase) in text_lower for phrase in HOLD_SYSTEM_PHRASES):
            self._enter_hold("system_phrase", original)
            return HoldResult(is_hold=True, hold_started=True)

        # Tier 2: Ambiguous hold → accumulate evidence
        if self._is_ambiguous_hold(text_lower):
            self._ambiguous_hits.append(time.monotonic())
            if self._check_ambiguous_threshold():
                self._enter_hold(f"ambiguous_x{self._ambiguous_threshold}", original)
                return HoldResult(is_hold=True, hold_started=True)

        return HoldResult(is_hold=False)

    def _detect_on_hold(self, text_lower: str, original: str) -> HoldResult:
        # FIX: >= 3 instead of > 3 (OptiBot bug: "Oui" is exactly 3 chars)
        if self._looks_like_human_return(text_lower) and len(text_lower) >= 3:
            self._hold_duration = time.monotonic() - self._hold_start
            logger.info("HOLD ENDED after %.0fs: '%s'", self._hold_duration, original[:80])
            self._on_hold = False
            return HoldResult(is_hold=False, hold_ended=True, duration=self._hold_duration)

        if time.monotonic() - self._hold_start > self._hold_timeout:
            self._hold_duration = self._hold_timeout
            logger.warning("HOLD TIMEOUT after %.0fs", self._hold_timeout)
            self._on_hold = False
            return HoldResult(is_hold=True, hold_timeout=True, duration=self._hold_timeout)

        # Still on hold — suppress
        return HoldResult(is_hold=True)

    def _is_ambiguous_hold(self, text_lower: str) -> bool:
        if any(_normalize_match_text(phrase) in text_lower for phrase in AGENT_WORKING_PHRASES):
            return False
        return any(_normalize_match_text(phrase) in text_lower for phrase in HOLD_AMBIGUOUS_PHRASES)

    def _looks_like_human_return(self, text_lower: str) -> bool:
        if any(_normalize_match_text(phrase) in text_lower for phrase in HUMAN_PHRASES):
            return True
        return any(
            phrase in text_lower
            for phrase in ("je reprends", "je reviens avec vous", "je suis de retour")
        )

    def _check_ambiguous_threshold(self) -> bool:
        now = time.monotonic()
        self._ambiguous_hits = [t for t in self._ambiguous_hits if now - t < self._ambiguous_window]
        return len(self._ambiguous_hits) >= self._ambiguous_threshold

    def _enter_hold(self, reason: str, text: str) -> None:
        self._on_hold = True
        self._hold_start = time.monotonic()
        self._ambiguous_hits.clear()
        logger.info("HOLD STARTED (%s): '%s'", reason, text[:80])

    def reset(self) -> None:
        """Reset state between calls."""
        self._on_hold = False
        self._hold_start = 0
        self._hold_duration = 0
        self._ambiguous_hits.clear()


class HoldResult:
    """Result of hold detection for a single transcription."""

    __slots__ = ("is_hold", "hold_started", "hold_ended", "hold_timeout", "duration")

    def __init__(
        self,
        is_hold: bool = False,
        hold_started: bool = False,
        hold_ended: bool = False,
        hold_timeout: bool = False,
        duration: float = 0,
    ):
        self.is_hold = is_hold
        self.hold_started = hold_started
        self.hold_ended = hold_ended
        self.hold_timeout = hold_timeout
        self.duration = duration

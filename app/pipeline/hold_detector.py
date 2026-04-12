"""Hold Music Detector v2 — two-tier confidence + scenario handlers.

Two-tier detection:
  - Tier 1 (HIGH): IVR/system phrases → instant hold (1 match)
  - Tier 2 (LOW): Ambiguous phrases → hold after 2 matches in 8s window
  - Agent working phrases ("je vérifie") cancel ambiguous signals

Phrase lists are data-driven: loaded from JSON files, overridable via env vars.
Fallback to hardcoded minimums only if no file found.

v2 changes (sourced from production research):
- C2 fix: prune _ambiguous_hits on every detect() call (not just on match)
- C3 fix: weak return hints (voilà, alors, bonjour) require ≥4 words + sentence-initial
- H2: extended French phrase corpus from real call center research
- H3: detect() returns reason + triggering_phrase for structured logging
- H5 fix: timeout returns is_hold=False so agent recovers
- L2 fix: reset() clearable across calls (caller must invoke)
- NEW: cold transfer detection ("je vous mets en relation")
- NEW: voicemail-dump pattern (Harmonie disconnect after long wait)

Hold timeout kept at 1200s (20 min) — French research shows MGEN holds
average 15 min, dropping below this would cut real calls.
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
    override = os.getenv(env_var)
    if override:
        try:
            data = json.loads(Path(override).read_text(encoding="utf-8"))
            if isinstance(data, list):
                result = [s for s in data if isinstance(s, str)]
                return result
        except (OSError, json.JSONDecodeError):
            pass
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
    """Strip combining marks (accents) and lowercase. NFKD normalization.

    Critical: must be applied to BOTH sides of any `in` substring check
    so that JSON phrases written without accents match real STT output
    that includes accents (and vice versa).
    """
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


# ── Tier 1: System/IVR hold phrases — NEVER said by a human agent ────
HOLD_SYSTEM_PHRASES = _load_phrase_list(
    "hold_system_phrases.json",
    "OPTIBOT_HOLD_SYSTEM_PHRASES_PATH",
    [
        "veuillez patienter", "merci de patienter", "merci de rester en ligne",
        "votre appel est important", "un conseiller va prendre",
        "vous etes en position", "nous allons prendre votre appel",
        "patientez quelques instants", "veuillez rester en ligne",
        "nous vous remercions de votre patience", "please hold", "please wait",
        "votre temps d'attente estime", "toutes nos lignes sont occupees",
        "nous recherchons votre correspondant", "nous allons donner suite",
    ],
)

# ── Tier 2: Ambiguous phrases — agents also say these ─────────────────
HOLD_AMBIGUOUS_PHRASES = _load_phrase_list(
    "hold_ambiguous_phrases.json",
    "OPTIBOT_HOLD_AMBIGUOUS_PHRASES_PATH",
    [
        "attendez", "un instant", "un moment", "ne quittez pas", "deux minutes",
        "en attente", "je vous mets en attente", "patientez",
    ],
)

# ── Strong human return phrases — high signal, no minimum word requirement ──
HUMAN_PHRASES = _load_phrase_list(
    "hold_human_phrases.json",
    "OPTIBOT_HOLD_HUMAN_PHRASES_PATH",
    [
        "comment puis-je vous aider", "je vous ecoute", "en quoi puis-je",
        "qui est a l appareil", "c est a quel sujet", "que puis-je faire",
        "j ai votre dossier", "j ai bien votre dossier",
        "merci de votre patience", "je vous remercie d avoir patiente",
        "excusez-moi pour l attente", "voila alors", "me revoici",
        "je suis de retour", "je reviens avec vous",
    ],
)

# ── Weak return hints — single discourse markers that are highest-signal ──
# in real French call centers BUT also common in office background chatter.
# These only end hold if they appear sentence-initial AND in a turn with
# at least MIN_RETURN_WORDS words (validates the speaker actually said
# something meaningful, not just a stray "alors" from a colleague's chat).
#
# Source: French mutuelle hold corpus research — these are the highest-signal
# "human is back" markers in real French call centers. Cannot remove them
# entirely without losing signal. Cannot accept them blindly without false
# positives from background voices.
WEAK_RETURN_HINTS = (
    "voila",   # extremely common discourse marker
    "alors",   # context resumption marker
    "donc",    # logical continuation marker
    "bon",     # transition marker
)
MIN_RETURN_WORDS = 4  # weak hints need ≥4 words in same turn

# ── Agent working phrases — cancel ambiguous hold signals ────────────
AGENT_WORKING_PHRASES = _load_phrase_list(
    "hold_agent_working_phrases.json",
    "OPTIBOT_HOLD_AGENT_WORKING_PATH",
    [
        "je verifie", "je cherche", "je recherche", "je vais chercher",
        "je regarde", "laissez-moi", "je vais voir", "je consulte",
        "je note", "je prends note", "j ouvre votre dossier",
    ],
)

# ── Cold transfer signals — agent passing call to a different person ──
# Different from regular hold: the next speaker may be a different
# interlocuteur entirely. Caller agent should NOT use the previous
# interlocuteur's name after detecting this.
COLD_TRANSFER_PHRASES = (
    "je vous mets en relation",
    "je vous transfere",
    "je vous transfert",
    "je vous passe",
    "je vais vous passer",
    "je vais vous transferer",
)

# ── Voicemail-dump signals — long wait followed by forced disconnect ──
# Harmonie pattern: "votre temps d'attente est de X minutes,
# rappelez ulterieurement" then disconnect. NOT a normal voicemail.
VOICEMAIL_DUMP_TRIGGERS = (
    "rappeler ulterieurement",
    "rappelez ulterieurement",
    "rappeler plus tard",
    "rappelez plus tard",
    "veuillez rappeler",
)


class HoldResult:
    """Result of hold detection for a single transcription."""

    __slots__ = (
        "is_hold", "hold_started", "hold_ended", "hold_timeout",
        "duration", "reason", "triggering_phrase",
        "cold_transfer_detected", "voicemail_dump_detected",
    )

    def __init__(
        self,
        is_hold: bool = False,
        hold_started: bool = False,
        hold_ended: bool = False,
        hold_timeout: bool = False,
        duration: float = 0,
        reason: str = "",
        triggering_phrase: str = "",
        cold_transfer_detected: bool = False,
        voicemail_dump_detected: bool = False,
    ):
        self.is_hold = is_hold
        self.hold_started = hold_started
        self.hold_ended = hold_ended
        self.hold_timeout = hold_timeout
        self.duration = duration
        self.reason = reason
        self.triggering_phrase = triggering_phrase
        self.cold_transfer_detected = cold_transfer_detected
        self.voicemail_dump_detected = voicemail_dump_detected


class HoldDetector:
    """Standalone hold music detector. No framework dependency.

    Usage:
        detector = HoldDetector()
        result = detector.detect("veuillez patienter")
        if result.is_hold:
            # suppress transcription, bot stays silent
        elif result.hold_ended:
            # human is back, resume conversation
        elif result.cold_transfer_detected:
            # different interlocuteur incoming — clear name memory
        elif result.voicemail_dump_detected:
            # call about to be disconnected by carrier — end gracefully
    """

    def __init__(
        self,
        hold_timeout_secs: float = 1200.0,  # 20 min — MGEN holds avg 15 min
        ambiguous_window_secs: float = 8.0,
        ambiguous_threshold: int = 2,
        min_return_words: int = 4,  # weak return hints need >= N words
    ):
        self._on_hold = False
        self._hold_start: float = 0
        self._hold_duration: float = 0
        self._hold_timeout = hold_timeout_secs
        self._ambiguous_window = ambiguous_window_secs
        self._ambiguous_threshold = ambiguous_threshold
        self._min_return_words = min_return_words
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
        """Process a transcription and return hold detection result."""
        text_lower = _normalize_match_text(text)
        if not text_lower:
            return HoldResult(is_hold=self._on_hold)

        # C2 FIX: prune ambiguous hits on EVERY detect call, not just
        # when another ambiguous fires. Prevents unbounded list growth
        # across long calls and removes ghost triggers.
        self._prune_ambiguous_hits()

        # Cold transfer is detectable in any state (hold or not)
        if self._matches_any(text_lower, COLD_TRANSFER_PHRASES):
            phrase = self._first_match(text_lower, COLD_TRANSFER_PHRASES)
            logger.info("COLD TRANSFER detected: '%s'", text[:80])
            return HoldResult(
                is_hold=self._on_hold,
                cold_transfer_detected=True,
                reason="cold_transfer",
                triggering_phrase=phrase,
            )

        # Voicemail-dump is detectable in any state
        if self._matches_any(text_lower, VOICEMAIL_DUMP_TRIGGERS):
            phrase = self._first_match(text_lower, VOICEMAIL_DUMP_TRIGGERS)
            logger.warning("VOICEMAIL DUMP pattern detected: '%s'", text[:80])
            return HoldResult(
                is_hold=self._on_hold,
                voicemail_dump_detected=True,
                reason="voicemail_dump",
                triggering_phrase=phrase,
            )

        if not self._on_hold:
            return self._detect_not_on_hold(text_lower, text)
        return self._detect_on_hold(text_lower, text)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _matches_any(text_lower: str, phrases) -> bool:
        return any(_normalize_match_text(p) in text_lower for p in phrases)

    @staticmethod
    def _first_match(text_lower: str, phrases) -> str:
        for p in phrases:
            if _normalize_match_text(p) in text_lower:
                return p
        return ""

    def _prune_ambiguous_hits(self) -> None:
        """C2 FIX: prune stale entries on every detect()."""
        now = time.monotonic()
        self._ambiguous_hits = [
            t for t in self._ambiguous_hits
            if now - t < self._ambiguous_window
        ]

    # ── Detection paths ──────────────────────────────────────────────

    def _detect_not_on_hold(self, text_lower: str, original: str) -> HoldResult:
        # Tier 1: System hold → instant trigger
        if self._matches_any(text_lower, HOLD_SYSTEM_PHRASES):
            phrase = self._first_match(text_lower, HOLD_SYSTEM_PHRASES)
            self._enter_hold("system_phrase", original)
            return HoldResult(
                is_hold=True,
                hold_started=True,
                reason="system_phrase",
                triggering_phrase=phrase,
            )

        # Tier 2: Ambiguous hold → accumulate evidence
        if self._is_ambiguous_hold(text_lower):
            self._ambiguous_hits.append(time.monotonic())
            if len(self._ambiguous_hits) >= self._ambiguous_threshold:
                phrase = self._first_match(text_lower, HOLD_AMBIGUOUS_PHRASES)
                self._enter_hold(f"ambiguous_x{self._ambiguous_threshold}", original)
                return HoldResult(
                    is_hold=True,
                    hold_started=True,
                    reason=f"ambiguous_x{self._ambiguous_threshold}",
                    triggering_phrase=phrase,
                )

        return HoldResult(is_hold=False)

    def _detect_on_hold(self, text_lower: str, original: str) -> HoldResult:
        # Strong return phrases: instant exit
        strong_match = self._first_match(text_lower, HUMAN_PHRASES)
        if strong_match:
            return self._exit_hold("strong_return", strong_match, original)

        # Weak return hints (voila/alors/donc/bon): require sentence-initial
        # + minimum word count to avoid false positives from office chatter
        weak_match = self._matches_weak_return(text_lower)
        if weak_match:
            return self._exit_hold("weak_return_with_context", weak_match, original)

        # Timeout check
        if time.monotonic() - self._hold_start > self._hold_timeout:
            self._hold_duration = self._hold_timeout
            logger.warning("HOLD TIMEOUT after %.0fs", self._hold_timeout)
            self._on_hold = False
            self._hold_start = 0  # M2 fix: reset start so duration is consistent
            # H5 FIX: return is_hold=False so agent can recover, not flap
            return HoldResult(
                is_hold=False,
                hold_timeout=True,
                duration=self._hold_timeout,
                reason="timeout",
            )

        # Still on hold — suppress
        return HoldResult(is_hold=True, reason="still_on_hold")

    def _matches_weak_return(self, text_lower: str) -> str:
        """C3 FIX: weak hints require sentence-initial + ≥4 words.

        Returns the matching weak hint if conditions met, empty string otherwise.
        """
        words = text_lower.split()
        if len(words) < self._min_return_words:
            return ""
        first_word = words[0]
        for hint in WEAK_RETURN_HINTS:
            if first_word == hint:
                return hint
        return ""

    def _exit_hold(self, reason: str, triggering: str, original: str) -> HoldResult:
        duration = time.monotonic() - self._hold_start
        self._hold_duration = duration
        self._on_hold = False
        self._hold_start = 0
        logger.info(
            "HOLD ENDED after %.0fs (reason=%s, trigger='%s'): '%s'",
            duration, reason, triggering, original[:80],
        )
        return HoldResult(
            is_hold=False,
            hold_ended=True,
            duration=duration,
            reason=reason,
            triggering_phrase=triggering,
        )

    def _is_ambiguous_hold(self, text_lower: str) -> bool:
        if self._matches_any(text_lower, AGENT_WORKING_PHRASES):
            return False
        return self._matches_any(text_lower, HOLD_AMBIGUOUS_PHRASES)

    def _enter_hold(self, reason: str, text: str) -> None:
        self._on_hold = True
        self._hold_start = time.monotonic()
        self._ambiguous_hits.clear()
        logger.info("HOLD STARTED (%s): '%s'", reason, text[:80])

    def reset(self) -> None:
        """Reset state between calls. Call from agent.__init__ or shutdown."""
        self._on_hold = False
        self._hold_start = 0
        self._hold_duration = 0
        self._ambiguous_hits.clear()

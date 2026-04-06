"""Answering Machine Detection — Twilio AMD-inspired branching.

Determines if call was answered by human, voicemail, or unknown.
Uses async detection to avoid dead air (Twilio AsyncAmd pattern).

Detection sources:
1. LiveKit STT analysis of first few seconds
2. Silence duration analysis
3. Speech duration analysis (long greeting = voicemail)

Tuning parameters based on Twilio AMD best practices:
- MachineDetectionSpeechThreshold: 2400ms (speech > this = machine)
- MachineDetectionSpeechEndThreshold: 1200ms (end silence > this = greeting done)
- MachineDetectionSilenceTimeout: 5000ms (initial silence > this = unknown)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class AnsweredBy(StrEnum):
    HUMAN = "human"
    MACHINE_START = "machine_start"
    MACHINE_END_BEEP = "machine_end_beep"
    MACHINE_END_SILENCE = "machine_end_silence"
    FAX = "fax"
    UNKNOWN = "unknown"
    PENDING = "pending"


@dataclass
class AMDConfig:
    """Tuning parameters for French telephony AMD.

    French-specific adjustments (vs Twilio English defaults):
    - human_speech_max_ms raised from 1500 to 2000: French call center agents
      answer with longer greetings ("Allô bonjour, service remboursements,
      j'écoute") than English "Hello?" (~800ms). 2000ms covers typical French
      human greetings without overlapping voicemail (which runs 4-8s).
    - speech_threshold_ms kept at 2400: French voicemail greetings
      ("Vous êtes bien sur le répondeur de...") run 4-8 seconds, well above.

    Sources:
    - Twilio AMD best practices: MachineDetectionSpeechThreshold
    - Daily.co voicemail detection agent pattern
    - Reddit: 34% of outbound calls hit voicemail; French greeting patterns differ
    """
    # Max time to wait for detection result
    detection_timeout_sec: float = 30.0
    # Speech longer than this = likely machine/voicemail greeting
    speech_threshold_ms: float = 2400.0
    # Silence after speech longer than this = greeting ended
    speech_end_threshold_ms: float = 1200.0
    # Initial silence longer than this = unknown/dead line
    silence_timeout_ms: float = 5000.0
    # Very short speech = likely human (French "allô" ~800ms, full greeting ~2s)
    human_speech_max_ms: float = 2000.0


@dataclass
class AMDResult:
    answered_by: AnsweredBy = AnsweredBy.PENDING
    detection_duration_ms: float = 0.0
    confidence: float = 0.0
    first_speech_ms: float = 0.0
    total_speech_ms: float = 0.0


class AnsweringMachineDetector:
    """Async AMD — runs detection while call proceeds (no dead air).

    Usage:
        amd = AnsweringMachineDetector()
        # Feed speech events as they arrive:
        amd.on_speech_start()
        amd.on_speech_end(duration_ms=800)
        # Check result:
        result = amd.get_result()
    """

    def __init__(self, config: AMDConfig | None = None):
        self._config = config or AMDConfig()
        self._start_time = time.monotonic()
        self._first_speech_at: float | None = None
        self._speech_segments: list[float] = []
        self._total_speech_ms: float = 0
        self._result: AMDResult | None = None
        self._finalized = False

    def on_speech_start(self) -> None:
        """Called when VAD detects speech start."""
        if self._first_speech_at is None:
            self._first_speech_at = time.monotonic()

    def on_speech_end(self, duration_ms: float) -> None:
        """Called when a speech segment ends with its duration."""
        self._speech_segments.append(duration_ms)
        self._total_speech_ms += duration_ms
        self._evaluate()

    def on_silence(self, silence_duration_ms: float) -> None:
        """Called on extended silence detection."""
        if self._first_speech_at is None and silence_duration_ms > self._config.silence_timeout_ms:
            self._finalize(AnsweredBy.UNKNOWN, confidence=0.3)

    def _evaluate(self) -> None:
        """Evaluate detection based on accumulated speech data."""
        if self._finalized:
            return

        cfg = self._config

        # Single short utterance (< 1.5s) = likely human saying "Allo?"
        if len(self._speech_segments) == 1 and self._speech_segments[0] < cfg.human_speech_max_ms:
            self._finalize(AnsweredBy.HUMAN, confidence=0.8)
            return

        # Long continuous speech (> 2.4s) = likely voicemail greeting
        if any(seg > cfg.speech_threshold_ms for seg in self._speech_segments):
            self._finalize(AnsweredBy.MACHINE_START, confidence=0.85)
            return

        # Multiple short segments in rapid succession = likely human conversation
        if len(self._speech_segments) >= 2:
            avg = self._total_speech_ms / len(self._speech_segments)
            if avg < cfg.human_speech_max_ms:
                self._finalize(AnsweredBy.HUMAN, confidence=0.7)
                return

    def _finalize(self, answered_by: AnsweredBy, confidence: float) -> None:
        if self._finalized:
            return
        self._finalized = True
        elapsed = (time.monotonic() - self._start_time) * 1000
        self._result = AMDResult(
            answered_by=answered_by,
            detection_duration_ms=elapsed,
            confidence=confidence,
            first_speech_ms=(self._first_speech_at - self._start_time) * 1000 if self._first_speech_at else 0,
            total_speech_ms=self._total_speech_ms,
        )
        logger.info("AMD result: %s (confidence=%.0f%%, duration=%.0fms)",
                    answered_by, confidence * 100, elapsed)

    def get_result(self) -> AMDResult:
        """Get current detection result. May still be PENDING."""
        if self._result:
            return self._result

        # Check timeout
        elapsed = (time.monotonic() - self._start_time) * 1000
        if elapsed > self._config.detection_timeout_sec * 1000:
            self._finalize(AnsweredBy.UNKNOWN, confidence=0.2)
            return self._result

        return AMDResult()

    @property
    def is_decided(self) -> bool:
        return self._finalized

"""Tests for Answering Machine Detection — Twilio AMD-inspired."""
import time
import pytest
from app.pipeline.amd import AnsweringMachineDetector, AMDConfig, AnsweredBy, AMDResult


class TestHumanDetection:
    def test_short_speech_is_human(self):
        """Short utterance like 'Allo?' = human (Twilio: < speech_threshold)."""
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        amd.on_speech_end(800)  # 800ms = short greeting
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.HUMAN
        assert r.confidence >= 0.7

    def test_multiple_short_segments_is_human(self):
        """Multiple short speech segments = human conversation."""
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        amd.on_speech_end(600)
        amd.on_speech_end(400)
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.HUMAN

    def test_very_short_allo(self):
        """'Allo' is ~300ms."""
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        amd.on_speech_end(300)
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.HUMAN

    def test_french_full_greeting_is_human(self):
        """French agent: 'Allo bonjour, service remboursements, j'ecoute' ~1.8s = human."""
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        amd.on_speech_end(1800)
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.HUMAN
        assert r.confidence >= 0.7


class TestMachineDetection:
    def test_long_speech_is_machine(self):
        """Long greeting > 2400ms = voicemail (Twilio: speech_threshold)."""
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        amd.on_speech_end(3000)  # 3s greeting = voicemail
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.MACHINE_START
        assert r.confidence >= 0.8

    def test_custom_threshold(self):
        """Custom threshold for shorter voicemail greetings."""
        cfg = AMDConfig(speech_threshold_ms=1500.0, human_speech_max_ms=1400.0)
        amd = AnsweringMachineDetector(config=cfg)
        amd.on_speech_start()
        amd.on_speech_end(1600)
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.MACHINE_START


class TestUnknownOutcome:
    def test_initial_silence_is_unknown(self):
        """No speech + long silence = unknown (dead line)."""
        amd = AnsweringMachineDetector()
        amd.on_silence(6000)  # 6s silence > default 5000ms
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.UNKNOWN
        assert r.confidence < 0.5

    def test_timeout_is_unknown(self):
        """Detection timeout = unknown."""
        cfg = AMDConfig(detection_timeout_sec=0.01)  # 10ms timeout
        amd = AnsweringMachineDetector(config=cfg)
        time.sleep(0.02)
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.UNKNOWN

    def test_pending_before_any_input(self):
        amd = AnsweringMachineDetector()
        r = amd.get_result()
        assert r.answered_by == AnsweredBy.PENDING


class TestIsDecided:
    def test_not_decided_initially(self):
        amd = AnsweringMachineDetector()
        assert not amd.is_decided

    def test_decided_after_human(self):
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        amd.on_speech_end(500)
        assert amd.is_decided

    def test_decided_does_not_change(self):
        """Once decided, result is locked."""
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        amd.on_speech_end(500)  # human
        r1 = amd.get_result()
        amd.on_speech_end(5000)  # would be machine if not locked
        r2 = amd.get_result()
        assert r1.answered_by == r2.answered_by == AnsweredBy.HUMAN


class TestDetectionDuration:
    def test_duration_recorded(self):
        amd = AnsweringMachineDetector()
        amd.on_speech_start()
        time.sleep(0.05)
        amd.on_speech_end(500)
        r = amd.get_result()
        assert r.detection_duration_ms > 0

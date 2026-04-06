"""Tests for hold detector — two-tier confidence system."""
import time
import pytest
from app.pipeline.hold_detector import HoldDetector


class TestTier1SystemHold:
    def test_system_phrase_triggers_hold(self):
        d = HoldDetector()
        result = d.detect("veuillez patienter")
        assert result.is_hold
        assert result.hold_started
        assert d.on_hold

    def test_all_system_phrases(self):
        for phrase in ["votre appel est important", "toutes nos lignes sont occupées",
                       "nous allons prendre votre appel"]:
            d = HoldDetector()
            result = d.detect(phrase)
            assert result.is_hold, f"Failed for: {phrase}"

    def test_system_phrase_case_insensitive(self):
        d = HoldDetector()
        result = d.detect("VEUILLEZ PATIENTER")
        assert result.is_hold


class TestTier2AmbiguousHold:
    def test_single_ambiguous_no_hold(self):
        d = HoldDetector()
        result = d.detect("attendez")
        assert not result.is_hold

    def test_two_ambiguous_triggers_hold(self):
        d = HoldDetector()
        d.detect("attendez")
        result = d.detect("un instant")
        assert result.is_hold
        assert result.hold_started

    def test_agent_working_cancels_ambiguous(self):
        d = HoldDetector()
        result = d.detect("attendez, je vérifie votre dossier")
        assert not result.is_hold


class TestHoldEnd:
    def test_human_phrase_ends_hold(self):
        d = HoldDetector()
        d.detect("veuillez patienter")
        assert d.on_hold

        result = d.detect("bonjour, je reviens")
        assert not result.is_hold
        assert result.hold_ended
        assert not d.on_hold

    def test_oui_ends_hold_bugfix(self):
        """FIX: 'Oui' is exactly 3 chars. Old code had len > 3, now >= 3."""
        d = HoldDetector()
        d.detect("veuillez patienter")
        # "oui" is not in HUMAN_PHRASES but "alors" is (5 chars)
        result = d.detect("alors")
        assert result.hold_ended

    def test_short_text_does_not_end_hold(self):
        """Very short text (1-2 chars) should not end hold."""
        d = HoldDetector()
        d.detect("veuillez patienter")
        result = d.detect("ok")  # 2 chars, < 3
        assert result.is_hold  # still on hold


class TestHoldTimeout:
    def test_timeout_ends_hold(self):
        d = HoldDetector(hold_timeout_secs=0.1)
        d.detect("veuillez patienter")
        time.sleep(0.15)
        result = d.detect("still hold music")
        assert result.hold_timeout


class TestReset:
    def test_reset_clears_state(self):
        d = HoldDetector()
        d.detect("veuillez patienter")
        assert d.on_hold
        d.reset()
        assert not d.on_hold

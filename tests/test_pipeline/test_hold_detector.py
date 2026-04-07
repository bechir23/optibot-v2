"""Tests for hold detector v2 — two-tier confidence + scenario handlers."""
import time
import pytest
from app.pipeline.hold_detector import HoldDetector


class TestTier1SystemHold:
    def test_system_phrase_triggers_hold(self):
        d = HoldDetector()
        result = d.detect("veuillez patienter")
        assert result.is_hold
        assert result.hold_started
        assert result.reason == "system_phrase"
        assert "patienter" in result.triggering_phrase
        assert d.on_hold

    def test_all_system_phrases(self):
        for phrase in [
            "votre appel est important",
            "toutes nos lignes sont occupees",
            "nous allons prendre votre appel",
            "nous recherchons votre correspondant",  # NEW
        ]:
            d = HoldDetector()
            result = d.detect(phrase)
            assert result.is_hold, f"Failed for: {phrase}"

    def test_system_phrase_case_insensitive(self):
        d = HoldDetector()
        result = d.detect("VEUILLEZ PATIENTER")
        assert result.is_hold

    def test_system_phrase_accent_insensitive(self):
        """H1 fix: STT output with accents must match unaccented JSON phrases."""
        d = HoldDetector()
        # Real Deepgram French output includes accents
        result = d.detect("toutes nos lignes sont occupées")
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

    def test_je_vous_mets_en_attente(self):
        """NEW: French corpus phrase added in v2."""
        d = HoldDetector()
        # Single ambiguous = no immediate trigger; 2 in window = trigger
        d.detect("je vous mets en attente")
        result = d.detect("un moment")
        assert result.is_hold


class TestHoldEnd:
    def test_strong_human_phrase_ends_hold(self):
        """Strong return phrases (no word count requirement)."""
        d = HoldDetector()
        d.detect("veuillez patienter")
        assert d.on_hold
        result = d.detect("merci de votre patience, j'ai votre dossier")
        assert not result.is_hold
        assert result.hold_ended
        assert result.reason == "strong_return"
        assert not d.on_hold

    def test_voila_with_context_ends_hold(self):
        """C3 fix: weak hint 'voila' ends hold ONLY with ≥4 words.

        Note: 'voila alors' is also a strong return phrase (added in v2),
        so it would match the strong path first. This test uses 'donc'
        which is ONLY in WEAK_RETURN_HINTS.
        """
        d = HoldDetector()
        d.detect("veuillez patienter")
        result = d.detect("donc apres verification le dossier est en cours")
        assert result.hold_ended
        assert result.reason == "weak_return_with_context"
        assert result.triggering_phrase == "donc"

    def test_strong_return_phrase_voila_alors(self):
        """voila alors is added as a strong return phrase in v2."""
        d = HoldDetector()
        d.detect("veuillez patienter")
        result = d.detect("voila alors j'ai trouve")
        assert result.hold_ended
        assert result.reason == "strong_return"

    def test_alors_alone_does_not_end_hold(self):
        """C3 fix: bare 'alors' from background chatter must NOT end hold."""
        d = HoldDetector()
        d.detect("veuillez patienter")
        result = d.detect("alors")
        assert not result.hold_ended  # Too short, ignored
        assert result.is_hold  # Still on hold

    def test_alors_in_short_chatter_does_not_end_hold(self):
        """C3 fix: short utterances with weak hints stay on hold."""
        d = HoldDetector()
        d.detect("veuillez patienter")
        # 3 words, weak hint sentence-initial — STILL not enough
        result = d.detect("alors voila bon")
        assert result.is_hold
        assert not result.hold_ended

    def test_voila_not_sentence_initial_does_not_end_hold(self):
        """Weak hint must be sentence-initial."""
        d = HoldDetector()
        d.detect("veuillez patienter")
        # voila is 4th word — not sentence-initial
        result = d.detect("la la la voila c est fini")
        assert not result.hold_ended


class TestHoldTimeout:
    def test_timeout_returns_is_hold_false(self):
        """H5 fix: timeout returns is_hold=False so agent recovers."""
        d = HoldDetector(hold_timeout_secs=0.1)
        d.detect("veuillez patienter")
        time.sleep(0.15)
        result = d.detect("still hold music")
        assert result.hold_timeout
        assert result.is_hold is False  # H5: agent must recover, not flap
        assert not d.on_hold


class TestReset:
    def test_reset_clears_state(self):
        d = HoldDetector()
        d.detect("veuillez patienter")
        assert d.on_hold
        d.reset()
        assert not d.on_hold
        assert not d._ambiguous_hits

    def test_reset_clears_ambiguous_hits(self):
        d = HoldDetector()
        d.detect("attendez")  # 1 hit
        d.reset()
        # Next ambiguous should be a fresh hit count
        d.detect("un instant")
        assert not d.on_hold  # Only 1 hit after reset


class TestAmbiguousPruning:
    def test_ambiguous_hits_pruned_on_every_detect(self):
        """C2 fix: prune on every detect, not just on ambiguous match."""
        d = HoldDetector(ambiguous_window_secs=0.05)
        d.detect("attendez")  # 1 hit
        time.sleep(0.1)  # Wait past window
        # Non-ambiguous turn — must prune the stale hit
        d.detect("bonjour bonjour bonjour")
        assert len(d._ambiguous_hits) == 0

    def test_unbounded_growth_prevented(self):
        """C2 fix: list does not grow unbounded across many turns."""
        d = HoldDetector(ambiguous_window_secs=0.05)
        for _ in range(100):
            d.detect("attendez")
            time.sleep(0.001)
        time.sleep(0.1)  # All stale
        d.detect("hello world")
        assert len(d._ambiguous_hits) == 0


class TestColdTransfer:
    """NEW scenario: agent passes call to a different person."""

    def test_cold_transfer_detected(self):
        d = HoldDetector()
        result = d.detect("je vous mets en relation avec le service tiers payant")
        assert result.cold_transfer_detected
        assert result.reason == "cold_transfer"

    def test_cold_transfer_works_during_hold(self):
        d = HoldDetector()
        d.detect("veuillez patienter")
        result = d.detect("je vous transfere au service comptabilite")
        assert result.cold_transfer_detected


class TestVoicemailDump:
    """NEW scenario: Harmonie pattern — long wait then forced disconnect."""

    def test_voicemail_dump_detected(self):
        d = HoldDetector()
        result = d.detect("votre temps d'attente est de 12 minutes, veuillez rappeler ulterieurement")
        assert result.voicemail_dump_detected
        assert result.reason == "voicemail_dump"

    def test_rappelez_plus_tard_detected(self):
        d = HoldDetector()
        result = d.detect("nos services sont surcharges, veuillez rappeler plus tard")
        assert result.voicemail_dump_detected


class TestRealCallScenarios:
    """End-to-end scenarios from French call center research."""

    def test_mgen_long_hold_simulated(self):
        """5-min MGEN-style hold with check-in midway, then return."""
        d = HoldDetector(hold_timeout_secs=600.0)
        # Agent puts caller on hold
        result = d.detect("merci de patienter, je consulte votre dossier")
        assert result.is_hold

        # Agent comes back with strong return phrase
        result = d.detect("merci de votre patience, j'ai bien votre dossier sous les yeux")
        assert result.hold_ended
        assert result.reason == "strong_return"

    def test_je_verifie_then_silence_then_info_pattern(self):
        """Common pattern: agent says je verifie, silence, returns with info."""
        d = HoldDetector()
        # je verifie cancels ambiguous, doesn't trigger hold by itself
        result = d.detect("attendez, je verifie")
        assert not result.is_hold
        # Then real info — strong return
        result = d.detect("voila alors j'ai trouve votre reference")
        # Not on hold, so weak return is informational only
        assert not result.is_hold

    def test_normal_conversation_no_false_hold(self):
        """Random French conversation must not trigger hold."""
        d = HoldDetector()
        for phrase in [
            "bonjour je vous appelle pour un dossier",
            "le numero est BRD-2024-12345",
            "le patient s'appelle Jean Dupont",
            "vous pouvez me confirmer le statut",
        ]:
            result = d.detect(phrase)
            assert not result.is_hold, f"False positive on: {phrase}"

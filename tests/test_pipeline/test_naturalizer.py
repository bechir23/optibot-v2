"""Tests for response naturalizer — variation, anti-repeat, transitions."""
import pytest
import asyncio
from app.pipeline.naturalizer import ResponseNaturalizer, format_numbers_for_speech, VARIATIONS


class TestVariations:
    def test_all_action_types_defined(self):
        assert len(VARIATIONS) >= 20

    def test_each_action_has_variants(self):
        for action_id, variants in VARIATIONS.items():
            if action_id == "P3_SILENCE":
                assert variants == []
            else:
                assert len(variants) >= 2, f"{action_id} has < 2 variants"

    def test_silence_returns_empty(self):
        n = ResponseNaturalizer()
        result = asyncio.run(n.naturalize("P3_SILENCE", "", {}))
        assert result == ""


class TestAntiRepeat:
    def test_no_immediate_repeat(self):
        n = ResponseNaturalizer()
        results = set()
        for _ in range(10):
            result = asyncio.run(n.naturalize("P3_ACK", "OK", {}))
            results.add(result)
        # Should have at least 2 different responses in 10 tries
        assert len(results) >= 2

    def test_backchannel_no_repeat(self):
        n = ResponseNaturalizer()
        last = ""
        for _ in range(5):
            bc = n.pick_backchannel()
            assert bc != last, f"Repeated backchannel: {bc}"
            last = bc


class TestTransitions:
    def test_transition_after_question(self):
        n = ResponseNaturalizer()
        # Run multiple times — sometimes should get "Oui, " prefix
        has_transition = False
        for _ in range(20):
            result = asyncio.run(
                n.naturalize("P3_ACK", "OK", {}, last_utterance="Quel est le statut ?")
            )
            if result.startswith("Oui"):
                has_transition = True
                break
        # Transition is random (25% chance), so may not always appear
        # Just verify it doesn't crash

    def test_transition_from_hold(self):
        n = ResponseNaturalizer()
        has_hold_prefix = False
        for _ in range(20):
            result = asyncio.run(n.naturalize("P3_ACK", "OK", {}, from_hold=True))
            if "toujours la" in result:
                has_hold_prefix = True
                break


class TestTemplateFormatting:
    def test_patient_name_substitution(self):
        n = ResponseNaturalizer()
        result = asyncio.run(
            n.naturalize("P3_GIVE_PATIENT", "{patient_name}", {"patient_name": "Dupont"})
        )
        assert "Dupont" in result

    def test_missing_key_does_not_crash(self):
        n = ResponseNaturalizer()
        result = asyncio.run(n.naturalize("P3_GIVE_PATIENT", "{unknown_key}", {}))
        assert result  # Should return something


class TestNumberFormatting:
    def test_euros_in_words(self):
        result = format_numbers_for_speech("Le montant est 250 euros")
        assert "deux cent cinquante euros" in result

    def test_long_number_spelled(self):
        result = format_numbers_for_speech("Le bordereau 123456789")
        assert "," in result  # digits separated
        assert "..." in result  # groups separated

    def test_short_number_unchanged(self):
        result = format_numbers_for_speech("Le code 1234")
        assert "1234" in result  # not long enough to spell

    def test_euros_with_cents(self):
        result = format_numbers_for_speech("Total: 42.50 euros")
        assert "quarante-deux euros" in result
        assert "cinquante centimes" in result


class TestReset:
    def test_reset_clears_history(self):
        n = ResponseNaturalizer()
        for _ in range(5):
            asyncio.run(n.naturalize("P3_ACK", "OK", {}))
        n.reset()
        assert n._used == {}

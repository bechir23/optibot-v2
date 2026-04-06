"""Tests for fuzzy mutuelle name matching."""
import pytest
from app.pipeline.fuzzy_matching import match_mutuelle, KNOWN_MUTUELLES


class TestExactMatch:
    def test_known_mutuelle_matches(self):
        result = match_mutuelle("Harmonie Mutuelle")
        assert result == "Harmonie Mutuelle"

    def test_mgen_matches(self):
        result = match_mutuelle("MGEN")
        assert result == "MGEN"


class TestFuzzyMatch:
    def test_typo_matches(self):
        result = match_mutuelle("armoni mutuel")
        assert result is not None
        assert "Harmonie" in result

    def test_partial_match(self):
        result = match_mutuelle("malakoff")
        assert result is not None
        assert "Malakoff" in result

    def test_case_insensitive(self):
        result = match_mutuelle("axa")
        assert result == "AXA"


class TestNoMatch:
    def test_garbage_no_match(self):
        result = match_mutuelle("xyzabc123")
        assert result is None

    def test_empty_no_match(self):
        result = match_mutuelle("")
        assert result is None

    def test_low_score_rejected(self):
        result = match_mutuelle("restaurant", score_cutoff=80.0)
        assert result is None


class TestExtraChoices:
    def test_extra_choices_included(self):
        result = match_mutuelle("mutuelle optique plus", extra_choices=["Mutuelle Optique Plus"])
        assert result == "Mutuelle Optique Plus"


class TestKnownList:
    def test_minimum_mutuelles(self):
        assert len(KNOWN_MUTUELLES) >= 20

"""Tests for SSML normalizer — French telephony text normalization."""
import pytest
from app.pipeline.ssml_normalizer import normalize_for_tts, ABBREVIATIONS, _month_name


class TestAbbreviationExpansion:
    def test_cpam_expanded(self):
        result = normalize_for_tts("Contactez votre CPAM")
        assert "C.P.A.M." in result

    def test_nir_expanded(self):
        result = normalize_for_tts("Le NIR du patient")
        assert "répertoire" in result

    def test_finess_expanded(self):
        result = normalize_for_tts("Le numero FINESS")
        assert "F.I.N.E.S.S." in result

    def test_tp_expanded(self):
        result = normalize_for_tts("En tiers payant ou TP")
        assert "tiers payant" in result

    def test_multiple_abbreviations(self):
        result = normalize_for_tts("La CPAM et le NIR pour le TP")
        assert "C.P.A.M." in result
        assert "répertoire" in result
        assert "tiers payant" in result

    def test_all_abbreviations_defined(self):
        assert len(ABBREVIATIONS) >= 19


class TestPhoneNormalization:
    def test_french_phone_grouped(self):
        result = normalize_for_tts("Appelez le 01 42 68 53 00")
        assert "01, 42, 68, 53, 00" in result

    def test_phone_without_spaces(self):
        result = normalize_for_tts("Appelez le 0142685300")
        assert "01, 42, 68, 53, 00" in result


class TestLongNumberSpelling:
    def test_nir_spelled_out(self):
        result = normalize_for_tts("NIR 1234567890123")
        # Should be spelled in groups of 3 with pauses
        assert "..." in result
        assert "," in result

    def test_short_number_unchanged(self):
        result = normalize_for_tts("Le dossier 12345")
        # 5 digits: should NOT be spelled out
        assert "12345" in result


class TestEuroFormatting:
    def test_euros_in_words(self):
        result = normalize_for_tts("Le montant est 150 euros")
        assert "cent cinquante euros" in result

    def test_euros_with_cents(self):
        result = normalize_for_tts("Le montant est 779.91 euros")
        assert "sept cent soixante" in result
        assert "centimes" in result


class TestDateFormatting:
    def test_french_date_expanded(self):
        result = normalize_for_tts("La date est 25/12/2024")
        assert "décembre" in result

    def test_date_with_dashes(self):
        result = normalize_for_tts("Le 15-03-2025")
        assert "mars" in result


class TestMonthNames:
    def test_all_months(self):
        for m in ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]:
            assert _month_name(m) != m

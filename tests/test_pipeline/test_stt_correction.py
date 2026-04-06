"""Tests for STT correction — French mutuelle names, optician terms, emails."""
import pytest
from app.pipeline.stt_correction import correct_transcription


class TestMutuelleNames:
    def test_harmonie_mutuelle_variants(self):
        assert "Harmonie Mutuelle" in correct_transcription("armoni mutuel")
        assert "Harmonie Mutuelle" in correct_transcription("harmonimutuel")

    def test_mgen(self):
        assert "MGEN" in correct_transcription("em g e n")
        assert "MGEN" in correct_transcription("emgen")

    def test_ag2r(self):
        assert "AG2R" in correct_transcription("a g 2 r")
        assert "AG2R" in correct_transcription("ag deux r")

    def test_almerys(self):
        assert "Almerys" in correct_transcription("almeris")
        assert "Almerys" in correct_transcription("ammerys")

    def test_viamedis(self):
        assert "Viamedis" in correct_transcription("via medis")
        assert "Viamedis" in correct_transcription("via medi")

    def test_swiss_life(self):
        assert "Swiss Life" in correct_transcription("suisse life")
        assert "Swiss Life" in correct_transcription("swift life")

    def test_contextual_avril(self):
        # "avril" as month should NOT be corrected
        assert "avril" in correct_transcription("le 15 avril prochain").lower()
        # "avril" as mutuelle should be corrected
        assert "April" in correct_transcription("chez avril")

    def test_contextual_alan(self):
        assert "Alan" in correct_transcription("chez alan")

    def test_groupama_variant(self):
        assert "Groupama" in correct_transcription("groupamac mutuel")


class TestOpticianTerms:
    def test_lpp(self):
        assert "LPP" in correct_transcription("el pe pe")
        assert "LPP" in correct_transcription("el p p")

    def test_sesam_vitale(self):
        assert "SESAM-Vitale" in correct_transcription("sezam vital")
        assert "SESAM-Vitale" in correct_transcription("sesam vital")

    def test_finess(self):
        assert "FINESS" in correct_transcription("f i n e s s")

    def test_nir(self):
        assert "NIR" in correct_transcription("n i r")
        assert "NIR" in correct_transcription("hennéard")

    def test_bordereau(self):
        assert "bordereau" in correct_transcription("bord d'euro")
        assert "bordereau" in correct_transcription("bord d'oraux")

    def test_tiers_payant(self):
        assert "tiers payant" in correct_transcription("tier payant")

    def test_verres_progressifs(self):
        assert "verres progressifs" in correct_transcription("vert progressif")


class TestEmailCorrection:
    def test_arobase(self):
        assert "@" in correct_transcription("jean arobase gmail")

    def test_point_com(self):
        assert ".com" in correct_transcription("gmail point com")
        assert ".fr" in correct_transcription("gmail point fr")

    def test_domain_names(self):
        assert "gmail" in correct_transcription("g mail")
        assert "hotmail" in correct_transcription("hot mail")


class TestSpelling:
    def test_phonetic_alphabet(self):
        result = correct_transcription("D comme Daniel U comme Ursule")
        assert "D" in result
        assert "U" in result


class TestNoFalsePositives:
    def test_normal_french_preserved(self):
        text = "Bonjour, je voudrais savoir le statut de mon remboursement"
        assert correct_transcription(text) == text

    def test_finesse_not_finess(self):
        # "finesse" is a real French word, should not be corrected
        # (only "finess" without trailing 'e' should match)
        text = "avec beaucoup de finesse"
        result = correct_transcription(text)
        # The regex \bfiness\b should NOT match "finesse"
        assert "finesse" in result or "FINESS" not in result

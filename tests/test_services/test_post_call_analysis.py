"""Tests for post-call LLM analysis (Phase 7A, VAPI parity)."""
import pytest

from app.services.post_call_analysis import CallAnalysis, analyze_call


class TestCallAnalysis:
    def test_default_all_empty(self):
        a = CallAnalysis()
        assert a.statut == ""
        assert a.delai_jours == 0
        assert a.total_score() == 0

    def test_total_score_max(self):
        a = CallAnalysis(
            statut_obtained=1,
            delai_obtained=1,
            interlocuteur_known=1,
            call_resolved=1,
        )
        assert a.total_score() == 4

    def test_score_rubric_bounds(self):
        with pytest.raises(ValueError):
            CallAnalysis(statut_obtained=2)  # must be 0 or 1
        with pytest.raises(ValueError):
            CallAnalysis(statut_obtained=-1)

    def test_partial_extraction(self):
        a = CallAnalysis(
            statut="en_cours",
            delai_jours=10,
            interlocuteur_nom="Sophie",
            statut_obtained=1,
            delai_obtained=1,
            interlocuteur_known=1,
        )
        assert a.statut == "en_cours"
        assert a.delai_jours == 10
        assert a.total_score() == 3

    def test_fields_serializable(self):
        a = CallAnalysis(statut="paye", montant_paye=187.50)
        d = a.model_dump()
        assert d["statut"] == "paye"
        assert d["montant_paye"] == 187.50


class TestAnalyzeCallEmptyTranscript:
    @pytest.mark.asyncio
    async def test_empty_list_returns_defaults(self):
        result = await analyze_call([])
        assert result.total_score() == 0
        assert result.statut == ""

    @pytest.mark.asyncio
    async def test_only_system_messages_returns_defaults(self):
        result = await analyze_call([{"role": "system", "text": "dispatched"}])
        # System messages are filtered; no real content
        assert result.total_score() == 0


class TestAnalyzeCallMissingApiKey:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = await analyze_call([
            {"role": "agent", "text": "Bonjour"},
            {"role": "user", "text": "Bonjour, Harmonie"},
        ])
        # Without API key, returns defaults (non-critical failure)
        assert result.total_score() == 0

"""Tests for response queue — Dialogflow CX partial response pattern."""
import pytest
from app.pipeline.response_queue import ResponseQueue, pick_filler, select_conditional_response


class TestEnqueue:
    def test_enqueue_and_flush(self):
        q = ResponseQueue()
        q.enqueue("Bonjour")
        q.enqueue("Comment allez-vous ?")
        result = q.flush()
        assert result == ["Bonjour", "Comment allez-vous ?"]

    def test_flush_empties_queue(self):
        q = ResponseQueue()
        q.enqueue("Hello")
        q.flush()
        assert q.flush() == []

    def test_empty_text_ignored(self):
        q = ResponseQueue()
        q.enqueue("")
        q.enqueue("  ")
        assert q.flush() == []


class TestPriority:
    def test_lower_priority_first(self):
        q = ResponseQueue()
        q.enqueue("Low priority", priority=10)
        q.enqueue("High priority", priority=0)
        result = q.flush()
        assert result[0] == "High priority"


class TestPartialResponses:
    def test_partial_flush_separate(self):
        q = ResponseQueue()
        q.enqueue_partial("Un instant...")
        q.enqueue("Le dossier est traite.")
        partials = q.flush_partials()
        main = q.flush()
        assert partials == ["Un instant..."]
        assert main == ["Le dossier est traite."]

    def test_multiple_partials(self):
        q = ResponseQueue()
        q.enqueue_partial("Un instant...")
        q.enqueue_partial("Je verifie...")
        partials = q.flush_partials()
        assert len(partials) == 2


class TestNoRepeat:
    def test_no_immediate_repeat(self):
        q = ResponseQueue()
        q.enqueue("D'accord.")
        q.flush()  # records "D'accord." as recent
        q.enqueue("D'accord.")  # same text
        result = q.flush()
        assert result == []  # filtered as repeat

    def test_different_text_not_filtered(self):
        q = ResponseQueue()
        q.enqueue("D'accord.")
        q.flush()
        q.enqueue("Tres bien.")
        result = q.flush()
        assert result == ["Tres bien."]


class TestFiller:
    def test_pick_filler_returns_string(self):
        f = pick_filler("processing")
        assert isinstance(f, str)
        assert len(f) > 0

    def test_exclude_works(self):
        for _ in range(20):
            f = pick_filler("processing", exclude="Une seconde.")
            assert f != "Une seconde."


class TestConditionalResponse:
    def test_select_by_condition(self):
        responses = {
            "en_cours": ["Le dossier est en cours.", "Ca avance."],
            "rejete": ["Le dossier a ete rejete.", "Malheureusement, c'est rejete."],
            "default": ["Je vais verifier."],
        }
        result = select_conditional_response(responses, "en_cours")
        assert result in responses["en_cours"]

    def test_fallback_to_default(self):
        responses = {"default": ["Fallback"]}
        result = select_conditional_response(responses, "unknown_condition")
        assert result == "Fallback"

    def test_no_repeat(self):
        responses = {"a": ["X", "Y"]}
        results = set()
        for _ in range(20):
            r = select_conditional_response(responses, "a", last_used="X")
            results.add(r)
        # Should always pick Y when X is excluded
        assert "Y" in results

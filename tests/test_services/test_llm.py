"""Tests for LLM service — json-repair, tiktoken, truncation."""
import pytest
from app.services.llm import count_tokens, truncate_messages, repair_json_response


class TestTokenCounting:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_basic_text(self):
        tokens = count_tokens("Hello world")
        assert tokens > 0
        assert tokens < 10

    def test_french_text(self):
        tokens = count_tokens("Bonjour, je voudrais savoir le statut de mon remboursement")
        assert tokens > 0


class TestTruncateMessages:
    def test_under_budget_unchanged(self):
        msgs = [
            {"role": "system", "content": "Tu es un assistant."},
            {"role": "user", "content": "Bonjour"},
        ]
        result = truncate_messages(msgs, budget=1000)
        assert len(result) == 2

    def test_over_budget_truncates(self):
        msgs = [
            {"role": "system", "content": "System prompt."},
        ] + [
            {"role": "user", "content": f"Message {i} " * 100}
            for i in range(20)
        ]
        result = truncate_messages(msgs, budget=500)
        assert len(result) < len(msgs)
        assert result[0]["role"] == "system"  # System always kept

    def test_system_message_preserved(self):
        msgs = [
            {"role": "system", "content": "Important system prompt " * 50},
            {"role": "user", "content": "Hello"},
        ]
        result = truncate_messages(msgs, budget=5000)
        assert result[0]["role"] == "system"

    def test_empty_messages(self):
        assert truncate_messages([], budget=1000) == []


class TestJsonRepair:
    def test_valid_json_unchanged(self):
        assert repair_json_response('{"key": "value"}') == '{"key": "value"}'

    def test_trailing_comma(self):
        result = repair_json_response('{"key": "value",}')
        assert '"key"' in result
        assert '"value"' in result

    def test_missing_quotes(self):
        result = repair_json_response('{key: value}')
        # json-repair should fix this
        assert "key" in result

    def test_non_json_returns_something(self):
        text = "This is not JSON"
        result = repair_json_response(text)
        assert isinstance(result, str)

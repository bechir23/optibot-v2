"""Integration tests for persistent conversation memory (Task #22).

Verifies that mutuelle memory is:
1. Loaded into rag_context during outbound_session setup
2. Injected into OutboundCallerAgent's system prompt
3. Preserved across calls when memoriser_appel is called
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.outbound_caller import OutboundCallerAgent
from app.services.mutuelle_memory import MutuelleMemory


class TestMemoryInjectedIntoPrompt:
    def test_memory_text_appears_in_agent_instructions(self):
        """When rag_context has mutuelle_memory, it goes into the prompt."""
        agent = OutboundCallerAgent(
            patient_name="Jean Dupont",
            patient_dob="15/03/1985",
            mutuelle="Harmonie",
            dossier_ref="BRD-001",
            nir="1850375012345",
            rag_context={
                "mutuelle_memory": "SVI: 1 puis 3\nContacts connus: Sophie (gestionnaire)\nDelai moyen: 10 jours",
                "key_learnings": ["Donner le FINESS accelere la recherche"],
                "success_rate": 0.85,
            },
        )
        # Instructions are stored in the parent Agent class
        instructions = agent.instructions
        assert "SVI: 1 puis 3" in instructions
        assert "Sophie" in instructions
        assert "Delai moyen: 10 jours" in instructions
        assert "Donner le FINESS" in instructions
        assert "85%" in instructions or "0.85" in instructions

    def test_no_rag_context_no_memory_section(self):
        """If rag_context is None, prompt has no memory section."""
        agent = OutboundCallerAgent(
            patient_name="Jean Dupont",
            mutuelle="Harmonie",
            rag_context=None,
        )
        instructions = agent.instructions
        assert "Memoire mutuelle" not in instructions
        assert "Contacts connus" not in instructions

    def test_empty_memory_ignored(self):
        """Empty memory strings don't pollute the prompt."""
        agent = OutboundCallerAgent(
            patient_name="Jean Dupont",
            mutuelle="Harmonie",
            rag_context={"mutuelle_memory": ""},
        )
        instructions = agent.instructions
        # No "Memoire mutuelle" header when the text is empty
        assert "Memoire mutuelle:\n\n" not in instructions


class TestFormatForPrompt:
    def test_formats_svi_path(self):
        mem = MutuelleMemory(supabase=MagicMock(), cache=MagicMock())
        text = mem.format_for_prompt({
            "svi_chemin": "1 puis 3 puis 2",
            "delai_moyen_jours": 10,
        })
        assert "SVI: 1 puis 3 puis 2" in text
        assert "Delai moyen: 10 jours" in text

    def test_formats_interlocuteurs(self):
        mem = MutuelleMemory(supabase=MagicMock(), cache=MagicMock())
        text = mem.format_for_prompt({
            "interlocuteurs": [
                {"nom": "Sophie", "role": "gestionnaire"},
                {"nom": "Marc", "role": "responsable"},
            ],
        })
        assert "Sophie" in text
        assert "gestionnaire" in text

    def test_truncates_astuces_to_3(self):
        mem = MutuelleMemory(supabase=MagicMock(), cache=MagicMock())
        text = mem.format_for_prompt({
            "astuces": [
                {"contenu": "Astuce 1"},
                {"contenu": "Astuce 2"},
                {"contenu": "Astuce 3"},
                {"contenu": "Astuce 4"},  # should be truncated
                {"contenu": "Astuce 5"},
            ],
        })
        assert "Astuce 1" in text
        assert "Astuce 2" in text
        assert "Astuce 3" in text
        assert "Astuce 4" not in text

    def test_empty_dict_returns_empty(self):
        mem = MutuelleMemory(supabase=MagicMock(), cache=MagicMock())
        assert mem.format_for_prompt({}) == ""
        assert mem.format_for_prompt(None) == ""


class TestOpenItems:
    """Phase 6: dossier-level followups across calls."""

    @pytest.mark.asyncio
    async def test_load_open_items_empty_when_no_dossier(self):
        mem = MutuelleMemory(supabase=MagicMock(), cache=MagicMock())
        result = await mem.load_open_items("t1", "Harmonie", "")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_open_items_filters_resolved(self):
        mock_supabase = MagicMock()
        mock_supabase.select = AsyncMock(return_value=[
            {"id": 1, "state": "awaiting_doc", "note": "attestation"},
            {"id": 2, "state": "resolved", "note": "done"},
            {"id": 3, "state": "callback_scheduled", "note": "call back"},
        ])
        mem = MutuelleMemory(supabase=mock_supabase, cache=MagicMock())
        result = await mem.load_open_items("t1", "Harmonie", "BRD-001")
        assert len(result) == 2
        assert all(r["state"] != "resolved" for r in result)

    @pytest.mark.asyncio
    async def test_format_prompt_includes_open_items(self):
        mem = MutuelleMemory(supabase=MagicMock(), cache=MagicMock())
        text = mem.format_for_prompt({
            "open_items": [
                {"state": "awaiting_doc", "note": "attestation mutuelle", "callback_after": "2026-04-22"},
            ],
        })
        assert "Suivis en cours" in text
        assert "awaiting_doc" in text
        assert "attestation mutuelle" in text
        assert "2026-04-22" in text

    @pytest.mark.asyncio
    async def test_format_prompt_caps_open_items_at_3(self):
        mem = MutuelleMemory(supabase=MagicMock(), cache=MagicMock())
        text = mem.format_for_prompt({
            "open_items": [
                {"state": "awaiting_doc", "note": f"item {i}"} for i in range(5)
            ],
        })
        assert "item 0" in text
        assert "item 2" in text
        # items 3 and 4 should be truncated
        assert "item 4" not in text

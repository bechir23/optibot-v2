"""Tests for OutboundCallerAgent tool methods."""
import pytest

pytest.importorskip("livekit.agents", reason="livekit-agents dependency required for agent tests")

from app.agents.outbound_caller import OutboundCallerAgent


class TestAgentToolMethods:
    def test_agent_has_tool_methods(self):
        agent = OutboundCallerAgent(
            patient_name="Jean Dupont",
            mutuelle="MGEN",
            dossier_ref="BR-2024-001",
            montant=150.0,
        )
        tool_methods = [
            "give_patient_name",
            "give_dossier_reference",
            "give_date_of_birth",
            "give_nir",
            "give_montant",
            "ask_reimbursement_status",
            "ask_timeline",
            "ask_remaining_amount",
            "ask_reference_number",
            "ask_missing_documents",
            "extract_information",
            "end_call",
            "request_transfer",
            "acknowledge_and_wait",
            "escalate_to_human",
        ]
        for method_name in tool_methods:
            assert hasattr(agent, method_name), f"Missing tool: {method_name}"

    def test_agent_instructions_keep_context_without_pii(self):
        agent = OutboundCallerAgent(
            patient_name="Marie Martin",
            mutuelle="Harmonie Mutuelle",
            montant=250.0,
        )
        # PII must be served through tools, not embedded in system instructions.
        assert "Marie Martin" not in agent._instructions
        assert "Harmonie Mutuelle" in agent._instructions
        assert "250" not in agent._instructions

    def test_agent_instructions_with_rag(self):
        rag = {
            "key_learnings": ["Ask for reference early", "Hold time ~12min"],
            "success_rate": 0.78,
        }
        agent = OutboundCallerAgent(
            patient_name="Test",
            mutuelle="MGEN",
            rag_context=rag,
        )
        assert "78%" in agent._instructions
        assert "MGEN" in agent._instructions

    def test_extracted_data_initially_empty(self):
        agent = OutboundCallerAgent()
        assert agent.extracted_data == {}

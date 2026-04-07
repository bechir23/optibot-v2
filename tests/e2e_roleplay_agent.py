"""Roleplay evaluator for the current agent instructions and tool behavior.

This is a lightweight text-mode evaluator, useful before doing a real room test.
It does not replace LiveKit room testing, but it helps catch:
- bad first greetings
- banned wait phrases
- repeated "je verifie / un instant" behavior
- missing extraction/tool activity in simple scenarios
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

from livekit.agents import AgentSession
from livekit.plugins import openai as lk_openai

from app.agents.outbound_caller import OutboundCallerAgent
from app.config.settings import Settings


@dataclass
class Scenario:
    name: str
    call_mode: str
    turns: list[str]


SCENARIOS = {
    "inbound_greeting": Scenario(
        name="inbound_greeting",
        call_mode="inbound",
        turns=[
            "Bonjour",
            "Je voudrais des informations sur un remboursement de lunettes.",
            "C est au nom de Jean Dupont.",
        ],
    ),
    "outbound_mutuelle": Scenario(
        name="outbound_mutuelle",
        call_mode="outbound",
        turns=[
            "Bonjour, Harmonie Mutuelle service remboursements.",
            "C est pour quel patient ?",
            "Oui je vois le dossier. Le remboursement est en cours, comptez dix jours ouvres.",
        ],
    ),
}

BANNED_OPENERS = (
    "un instant",
    "je verifie",
    "je regarde",
    "laissez-moi verifier",
)


async def run_scenario(scenario: Scenario, model: str) -> int:
    settings = Settings()
    if not settings.openai_api_key:
        print("BLOCKED: OPENAI_API_KEY not set in environment or .env")
        return 2

    agent = OutboundCallerAgent(
        patient_name="Jean Dupont",
        patient_dob="15/03/1985",
        mutuelle="Harmonie Mutuelle",
        dossier_ref="BRD-2024-12345",
        montant=779.91,
        nir="1850375012345",
        dossier_type="optique",
        tenant_id="roleplay",
        call_id=f"roleplay-{scenario.name}",
        call_mode=scenario.call_mode,
    )

    problems = 0

    async with (
        lk_openai.LLM(model=model, api_key=settings.openai_api_key) as llm,
        AgentSession(llm=llm) as session,
    ):
        await session.start(agent)

        for idx, user_text in enumerate(scenario.turns, start=1):
            result = await session.run(user_input=user_text)
            reply = str(result.final_output)
            print(f"[User {idx}] {user_text}")
            print(f"[Agent {idx}] {reply}")
            print()

            lowered = reply.lower()
            if idx == 1 and any(phrase in lowered for phrase in BANNED_OPENERS):
                print("FAIL: first reply used a banned wait/verification phrase")
                problems += 1

        if not agent._tools_called:
            print("WARN: no tools were called in this roleplay")
        else:
            print(f"Tools called: {agent._tools_called}")

        if agent._extracted:
            print(f"Extracted: {agent._extracted}")

    if problems:
        print(f"RESULT: FAIL ({problems} issue(s))")
        return 1

    print("RESULT: PASS")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a text-mode roleplay against the current agent.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default="inbound_greeting",
    )
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args()

    raise SystemExit(asyncio.run(run_scenario(SCENARIOS[args.scenario], args.model)))


if __name__ == "__main__":
    main()

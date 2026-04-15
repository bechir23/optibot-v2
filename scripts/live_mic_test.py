"""Generate a LiveKit Meet URL to talk to the deployed OptiBot agent with your microphone.

Usage:
    python scripts/live_mic_test.py                       # default Harmonie scenario
    python scripts/live_mic_test.py --scenario mgen       # MGEN strict NIR scenario
    python scripts/live_mic_test.py --mutuelle "PRO BTP"  # custom mutuelle name

Then open the printed URL in your browser, click Connect, allow mic, and talk
to the agent. You play the role of the mutuelle operator.

The agent (deployed on LiveKit Cloud) connects automatically once you join the room.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import urllib.parse

from dotenv import load_dotenv

load_dotenv()


SCENARIOS = {
    "harmonie": {
        "mutuelle": "Harmonie Mutuelle",
        "patient_name": "Jean Dupont",
        "patient_dob": "15/03/1985",
        "dossier_ref": "BRD-2026-001",
        "montant": 779.91,
        "nir": "1850375012345",
        "tip": "Sophie au standard, vous donnez le statut 'en cours, 10 jours ouvres'.",
    },
    "mgen": {
        "mutuelle": "MGEN",
        "patient_name": "Jean Dupont",
        "patient_dob": "15/03/1985",
        "dossier_ref": "BRD-2026-002",
        "montant": 320.00,
        "nir": "1850375012345",
        "tip": "Marc au tiers payant, exigez le NIR avant TOUT autre info.",
    },
    "rejection": {
        "mutuelle": "AG2R La Mondiale",
        "patient_name": "Marie Martin",
        "patient_dob": "22/07/1972",
        "dossier_ref": "BRD-2026-003",
        "montant": 450.00,
        "nir": "2720775012345",
        "tip": "Annoncez un rejet: 'ordonnance perimee, plus de 5 ans'.",
    },
    "partial": {
        "mutuelle": "PRO BTP",
        "patient_name": "Pierre Durand",
        "patient_dob": "08/11/1968",
        "dossier_ref": "BRD-2026-004",
        "montant": 210.00,
        "nir": "1681175012345",
        "tip": "Paiement partiel: 120 EUR sur 210, depassement monture non couvert.",
    },
}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), default="harmonie")
    parser.add_argument("--agent-name", default=os.environ.get("AGENT_NAME", "optibot"))
    args = parser.parse_args()

    from livekit import api

    lk_url = os.environ["LIVEKIT_URL"]
    lk_http = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    key = os.environ["LIVEKIT_API_KEY"]
    secret = os.environ["LIVEKIT_API_SECRET"]
    room = f"live-{args.scenario}-{int(time.time()) % 100000}"

    scenario = SCENARIOS[args.scenario]
    metadata = {
        "tenant_id": f"live-mic-{args.scenario}",
        "local_loopback": True,
        "dossier": {
            "mutuelle": scenario["mutuelle"],
            "patient_name": scenario["patient_name"],
            "patient_dob": scenario["patient_dob"],
            "dossier_ref": scenario["dossier_ref"],
            "montant": scenario["montant"],
            "nir": scenario["nir"],
            "dossier_type": "optique",
        },
    }

    lk = api.LiveKitAPI(url=lk_http, api_key=key, api_secret=secret)
    await lk.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=args.agent_name, room=room, metadata=json.dumps(metadata)
        )
    )

    token = (
        api.AccessToken(api_key=key, api_secret=secret)
        .with_identity(f"tester-{int(time.time()) % 1000}")
        .with_name("Mic Tester")
        .with_grants(
            api.VideoGrants(
                room_join=True, room=room, can_publish=True, can_subscribe=True,
            )
        )
        .to_jwt()
    )
    await lk.aclose()

    meet_url = (
        f"https://meet.livekit.io/custom"
        f"?liveKitUrl={urllib.parse.quote(lk_url)}&token={token}"
    )

    print("\n" + "=" * 70)
    print(f" LIVE MIC TEST — Scenario: {args.scenario.upper()}")
    print("=" * 70)
    print(f" Mutuelle: {scenario['mutuelle']}")
    print(f" Patient:  {scenario['patient_name']} (DOB {scenario['patient_dob']})")
    print(f" Dossier:  {scenario['dossier_ref']} ({scenario['montant']} EUR)")
    print(f" Room:     {room}")
    print(f"\n YOUR ROLE: {scenario['tip']}")
    print(f"\n OPEN IN BROWSER:\n {meet_url}")
    print("\n Then: Connect → Allow mic → Speak French as the mutuelle operator.")
    print(" The OptiBot agent (opticien) will greet you and follow up on the dossier.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

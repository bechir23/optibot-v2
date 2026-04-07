"""Create a real LiveKit Cloud room, dispatch the deployed agent, and print a Meet URL.

This is a real-time validation helper for the active cloud deployment, not a unit test.
It intentionally exercises the deployed LiveKit path instead of local text-only fallbacks.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

load_dotenv(".env")

from livekit import api

from app.config.settings import Settings


def _build_metadata(args: argparse.Namespace) -> dict:
    dossier = {
        "patient_name": args.patient_name,
        "patient_dob": args.patient_dob,
        "mutuelle": args.mutuelle,
        "dossier_ref": args.dossier_ref,
        "montant": args.montant,
        "nir": args.nir,
        "dossier_type": args.dossier_type,
    }
    metadata: dict[str, object] = {
        "tenant_id": args.tenant_id,
        "local_loopback": args.local_loopback,
        "force_ivr": args.force_ivr,
        "dossier": dossier,
    }
    if args.phone_number:
        metadata["phone_number"] = args.phone_number
    return metadata


async def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch a real-time LiveKit room probe.")
    parser.add_argument("--tenant-id", default="manual-test")
    parser.add_argument("--patient-name", default="Jean Dupont")
    parser.add_argument("--patient-dob", default="15/03/1985")
    parser.add_argument("--mutuelle", default="Harmonie Mutuelle")
    parser.add_argument("--dossier-ref", default="BRD-2024-12345")
    parser.add_argument("--montant", type=float, default=779.91)
    parser.add_argument("--nir", default="1850375012345")
    parser.add_argument("--dossier-type", default="optique")
    parser.add_argument("--phone-number", default="")
    parser.add_argument("--local-loopback", dest="local_loopback", action="store_true")
    parser.add_argument("--sip-dial", dest="local_loopback", action="store_false")
    parser.add_argument("--force-ivr", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=20.0)
    parser.set_defaults(local_loopback=True)
    args = parser.parse_args()

    settings = Settings()
    room = f"optibot-live-{random.randint(100000, 999999)}"
    metadata = json.dumps(_build_metadata(args))

    lk = api.LiveKitAPI(
        url=settings.livekit_url.replace("ws://", "http://").replace("wss://", "https://"),
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=settings.agent_name,
                room=room,
                metadata=metadata,
            )
        )
        token = (
            api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity("caller")
            .with_name("Caller")
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )
        print(f"ROOM={room}")
        print(
            "URL="
            f"https://meet.livekit.io/custom?liveKitUrl={settings.livekit_url}&token={token}"
        )
        deadline = asyncio.get_running_loop().time() + max(0.0, args.wait_seconds)
        while asyncio.get_running_loop().time() < deadline:
            try:
                response = await lk.room.list_participants(
                    api.ListParticipantsRequest(room=room)
                )
            except Exception:
                participants = []
            else:
                participants = list(getattr(response, "participants", []) or [])
            if participants:
                identities = ",".join(p.identity for p in participants)
                print(f"PARTICIPANT_COUNT={len(participants)}")
                print(f"PARTICIPANTS={identities}")
                break
            await asyncio.sleep(1.0)
        else:
            print("PARTICIPANT_COUNT=0")
            print("PARTICIPANTS=")
    finally:
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(main())

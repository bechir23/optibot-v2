"""LiveKit real call tester with autodiscovery and concurrency support.

This script avoids hardcoded project or agent values whenever possible.

Examples:
    python scripts/test_live_call.py --discover-phone --agent-name my-agent
    python scripts/test_live_call.py +33600112233 --agent-name my-agent
    python scripts/test_live_call.py --inbound --inbound-number +33123456789
    python scripts/test_live_call.py --concurrent 5 --discover-phone --agent-name my-agent
    python scripts/test_live_call.py --localhost-mode outbound --agent-name my-agent
    python scripts/test_live_call.py --localhost-mode inbound --agent-name my-agent
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _normalize_phone(value: str) -> str:
    phone = value.strip().replace(" ", "").replace("-", "")
    # Handle frequent French variant +3306... -> +336...
    if phone.startswith("+330"):
        phone = "+33" + phone[4:]
    return phone


def _is_valid_e164(value: str) -> bool:
    return E164_RE.match(value) is not None


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _livekit_http_url() -> str:
    raw = _required_env("LIVEKIT_URL")
    if raw.startswith("wss://"):
        return "https://" + raw[len("wss://") :]
    if raw.startswith("ws://"):
        return "http://" + raw[len("ws://") :]
    return raw


def _infer_livekit_sip_uri() -> str:
    explicit = os.getenv("LIVEKIT_SIP_URI", "").strip()
    if explicit:
        return explicit

    host = urlparse(_livekit_http_url()).hostname or ""
    if host.endswith(".livekit.cloud"):
        subdomain = host.split(".")[0]
        return f"sip:{subdomain}.sip.livekit.cloud"
    return "<set LIVEKIT_SIP_URI>"


def _resolve_agent_name(explicit: str | None) -> str:
    if explicit:
        return explicit
    for env_name in ("LIVEKIT_AGENT_NAME", "AGENT_NAME"):
        val = os.getenv(env_name, "").strip()
        if val:
            return val
    raise RuntimeError(
        "Agent name is required. Pass --agent-name or set LIVEKIT_AGENT_NAME."
    )


def _resolve_sip_trunk_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    for env_name in (
        "TELNYX_SIP_TRUNK_ID",
        "SIP_OUTBOUND_TRUNK_ID",
        "LIVEKIT_SIP_TRUNK_ID",
    ):
        val = os.getenv(env_name, "").strip()
        if val:
            return val
    return ""


async def discover_twilio_numbers() -> dict[str, list[str]]:
    """Discover candidate numbers via Twilio APIs.

    Returns keys:
      - verified_outgoing
      - incoming_owned
    """
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        return {"verified_outgoing": [], "incoming_owned": []}

    verified: list[str] = []
    incoming: list[str] = []
    async with httpx.AsyncClient(timeout=20.0, auth=(sid, token)) as client:
        out = await client.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/OutgoingCallerIds.json"
        )
        if out.status_code == 200:
            payload = out.json()
            for item in payload.get("outgoing_caller_ids", []):
                phone = _normalize_phone(item.get("phone_number", ""))
                if _is_valid_e164(phone):
                    verified.append(phone)

        inc = await client.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json"
        )
        if inc.status_code == 200:
            payload = inc.json()
            for item in payload.get("incoming_phone_numbers", []):
                phone = _normalize_phone(item.get("phone_number", ""))
                if _is_valid_e164(phone):
                    incoming.append(phone)

    return {"verified_outgoing": verified, "incoming_owned": incoming}


def _pick_discovered_phone(numbers: dict[str, list[str]]) -> str | None:
    if numbers["verified_outgoing"]:
        return numbers["verified_outgoing"][0]
    if numbers["incoming_owned"]:
        return numbers["incoming_owned"][0]
    return None


def _print_join_hint(room_name: str) -> None:
    print("Join this room in real time (no PSTN needed):")
    print(
        f"  $lk=\"$env:USERPROFILE\\bin\\livekit-cli\\lk.exe\"; "
        f"& $lk room join {room_name} --identity local-tester --open meet"
    )


async def _dispatch_with_metadata(
    *,
    agent_name: str,
    metadata: dict[str, Any],
    room_prefix: str,
) -> tuple[str, str]:
    from livekit import api

    lk = api.LiveKitAPI(
        url=_livekit_http_url(),
        api_key=_required_env("LIVEKIT_API_KEY"),
        api_secret=_required_env("LIVEKIT_API_SECRET"),
    )

    tenant = str(metadata.get("tenant_id", "tenant-1") or "tenant-1")
    tenant_safe = re.sub(r"[^a-zA-Z0-9_-]", "_", tenant)
    room_name = f"{room_prefix}-{tenant_safe}-{int(time.time() * 1000) % 100000000}"
    started = time.monotonic()
    dispatch = await lk.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=agent_name,
            room=room_name,
            metadata=json.dumps(metadata),
        )
    )
    elapsed_ms = (time.monotonic() - started) * 1000.0

    print(
        f"Dispatch created: id={dispatch.id} room={dispatch.room} "
        f"elapsed={elapsed_ms:.0f}ms"
    )
    await lk.aclose()
    return dispatch.id, dispatch.room


async def _dispatch_call(
    *,
    agent_name: str,
    phone: str,
    tenant: str,
    mutuelle: str,
    dossier_type: str,
    patient_name: str,
    patient_dob: str,
    dossier_ref: str,
    montant: float,
    nir: str,
    sip_trunk_id: str,
) -> tuple[str, str]:
    metadata: dict[str, Any] = {
        "phone_number": phone,
        "tenant_id": tenant,
        "dossier": {
            "mutuelle": mutuelle,
            "dossier_type": dossier_type,
            "patient_name": patient_name,
            "patient_dob": patient_dob,
            "dossier_ref": dossier_ref,
            "montant": montant,
            "nir": nir,
        },
    }
    if sip_trunk_id:
        metadata["sip_trunk_id"] = sip_trunk_id

    return await _dispatch_with_metadata(
        agent_name=agent_name,
        metadata=metadata,
        room_prefix="call",
    )


async def _dispatch_localhost(
    *,
    agent_name: str,
    tenant: str,
    mode: str,
    mutuelle: str,
    dossier_type: str,
    patient_name: str,
    patient_dob: str,
    dossier_ref: str,
    montant: float,
    nir: str,
    caller_number: str,
    force_ivr: bool,
    ivr_path: str,
    target_service: str,
) -> tuple[str, str]:
    metadata: dict[str, Any] = {
        "tenant_id": tenant,
        "test_mode": f"localhost_{mode}",
    }

    if mode == "outbound":
        metadata["local_loopback"] = True
        metadata["dossier"] = {
            "mutuelle": mutuelle,
            "dossier_type": dossier_type,
            "patient_name": patient_name,
            "patient_dob": patient_dob,
            "dossier_ref": dossier_ref,
            "montant": montant,
            "nir": nir,
        }
        if force_ivr:
            metadata["force_ivr"] = True
            path_steps = [step.strip() for step in ivr_path.split(",") if step.strip()]
            metadata["known_ivr_tree"] = {
                "path_to_reimbursement": path_steps,
                "notes": "localhost simulation",
            }
            metadata["target_service"] = target_service
    else:
        metadata["caller_number"] = caller_number

    return await _dispatch_with_metadata(
        agent_name=agent_name,
        metadata=metadata,
        room_prefix="local",
    )


async def _monitor_room(room_name: str, timeout_sec: int) -> None:
    from livekit import api

    lk = api.LiveKitAPI(
        url=_livekit_http_url(),
        api_key=_required_env("LIVEKIT_API_KEY"),
        api_secret=_required_env("LIVEKIT_API_SECRET"),
    )
    start = time.monotonic()
    while (time.monotonic() - start) < timeout_sec:
        rooms = await lk.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
        if not rooms.rooms:
            print(f"Room deleted/end detected: {room_name}")
            break
        room = rooms.rooms[0]
        print(
            f"Room={room.name} participants={room.num_participants} "
            f"publishers={room.num_publishers}"
        )
        await asyncio.sleep(3)
    await lk.aclose()


async def run_outbound(args: argparse.Namespace) -> None:
    agent_name = _resolve_agent_name(args.agent_name)
    target = args.phone
    if target:
        target = _normalize_phone(target)
    elif args.discover_phone:
        discovered = await discover_twilio_numbers()
        picked = _pick_discovered_phone(discovered)
        if not picked:
            raise RuntimeError(
                "No phone discovered. Provide a phone argument or configure Twilio creds."
            )
        target = picked
        print(f"Discovered phone candidate: {target}")
    else:
        raise RuntimeError(
            "Target phone required. Pass a phone or use --discover-phone."
        )

    if not _is_valid_e164(target):
        raise RuntimeError(f"Invalid E.164 number after normalization: {target}")

    sip_trunk_id = _resolve_sip_trunk_id(args.sip_trunk_id)
    if sip_trunk_id:
        print(f"Using SIP trunk: {sip_trunk_id}")
    else:
        print("No SIP trunk configured in args/env; metadata will omit sip_trunk_id")

    if args.concurrent > 1:
        print(f"Running concurrent outbound test with {args.concurrent} calls")
        tasks = []
        for i in range(args.concurrent):
            tenant = f"tenant-{i + 1}"
            dossier_ref = f"TEST-{tenant}-{int(time.time()) % 100000:05d}"
            tasks.append(
                _dispatch_call(
                    agent_name=agent_name,
                    phone=target,
                    tenant=tenant,
                    mutuelle=args.mutuelle,
                    dossier_type=args.dossier_type,
                    patient_name=args.patient_name,
                    patient_dob=args.patient_dob,
                    dossier_ref=dossier_ref,
                    montant=args.montant,
                    nir=args.nir,
                    sip_trunk_id=sip_trunk_id,
                )
            )
        results = await asyncio.gather(*tasks)
        for _, room in results:
            await _monitor_room(room, args.monitor_seconds)
        return

    tenant = args.tenant or "tenant-1"
    dossier_ref = args.dossier_ref or f"TEST-{int(time.time()) % 100000:05d}"
    _, room = await _dispatch_call(
        agent_name=agent_name,
        phone=target,
        tenant=tenant,
        mutuelle=args.mutuelle,
        dossier_type=args.dossier_type,
        patient_name=args.patient_name,
        patient_dob=args.patient_dob,
        dossier_ref=dossier_ref,
        montant=args.montant,
        nir=args.nir,
        sip_trunk_id=sip_trunk_id,
    )
    await _monitor_room(room, args.monitor_seconds)


async def run_localhost(args: argparse.Namespace) -> None:
    """Dispatch no-phone localhost sessions for real-time interaction.

    outbound mode:
      - uses outbound_session with local_loopback=true (no SIP dial)
    inbound mode:
      - uses inbound_session path (no phone_number metadata)
    """
    agent_name = _resolve_agent_name(args.agent_name)
    mode = args.localhost_mode

    print("Localhost mode active: no external phone number will be dialed.")
    if mode == "outbound" and args.force_ivr:
        print(
            "IVR simulation enabled: navigation agent will run in loopback mode "
            f"with path={args.ivr_path}."
        )
    if mode == "inbound" and args.force_ivr:
        print("Ignoring --force-ivr in inbound localhost mode.")

    if args.concurrent > 1:
        print(f"Running concurrent localhost {mode} test with {args.concurrent} sessions")
        tasks = []
        for i in range(args.concurrent):
            tenant = f"tenant-{i + 1}"
            dossier_ref = f"LOCAL-{tenant}-{int(time.time()) % 100000:05d}"
            tasks.append(
                _dispatch_localhost(
                    agent_name=agent_name,
                    tenant=tenant,
                    mode=mode,
                    mutuelle=args.mutuelle,
                    dossier_type=args.dossier_type,
                    patient_name=args.patient_name,
                    patient_dob=args.patient_dob,
                    dossier_ref=dossier_ref,
                    montant=args.montant,
                    nir=args.nir,
                    caller_number=args.caller_number,
                    force_ivr=args.force_ivr,
                    ivr_path=args.ivr_path,
                    target_service=args.target_service,
                )
            )

        results = await asyncio.gather(*tasks)
        for _, room in results:
            _print_join_hint(room)
        for _, room in results:
            await _monitor_room(room, args.monitor_seconds)
        return

    tenant = args.tenant or "tenant-1"
    dossier_ref = args.dossier_ref or f"LOCAL-{int(time.time()) % 100000:05d}"
    _, room = await _dispatch_localhost(
        agent_name=agent_name,
        tenant=tenant,
        mode=mode,
        mutuelle=args.mutuelle,
        dossier_type=args.dossier_type,
        patient_name=args.patient_name,
        patient_dob=args.patient_dob,
        dossier_ref=dossier_ref,
        montant=args.montant,
        nir=args.nir,
        caller_number=args.caller_number,
        force_ivr=args.force_ivr,
        ivr_path=args.ivr_path,
        target_service=args.target_service,
    )

    _print_join_hint(room)
    await _monitor_room(room, args.monitor_seconds)


async def run_inbound(args: argparse.Namespace) -> None:
    from livekit import api

    inbound_number = args.inbound_number or os.getenv("TWILIO_PHONE_NUMBER", "").strip()
    if inbound_number:
        inbound_number = _normalize_phone(inbound_number)

    print("Inbound test mode")
    print(f"Call this number from a real phone: {inbound_number or '<set --inbound-number>'}")
    print(f"Expected LiveKit SIP URI: {_infer_livekit_sip_uri()}")
    print("Watching for newly created rooms during inbound call window...")

    lk = api.LiveKitAPI(
        url=_livekit_http_url(),
        api_key=_required_env("LIVEKIT_API_KEY"),
        api_secret=_required_env("LIVEKIT_API_SECRET"),
    )
    initial = await lk.room.list_rooms(api.ListRoomsRequest())
    known = {r.name for r in initial.rooms}

    start = time.monotonic()
    while (time.monotonic() - start) < args.monitor_seconds:
        snapshot = await lk.room.list_rooms(api.ListRoomsRequest())
        current = {r.name for r in snapshot.rooms}
        new_rooms = sorted(current - known)
        for room_name in new_rooms:
            room = next((r for r in snapshot.rooms if r.name == room_name), None)
            if room:
                print(
                    f"New room detected: {room.name} "
                    f"participants={room.num_participants} publishers={room.num_publishers}"
                )
        known = current
        await asyncio.sleep(2)

    await lk.aclose()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Realtime LiveKit call tester")
    p.add_argument("phone", nargs="?", help="Target outbound number in E.164")
    p.add_argument("--discover-phone", action="store_true", help="Auto-discover phone via Twilio API")
    p.add_argument("--agent-name", help="Agent name to dispatch")
    p.add_argument(
        "--localhost-mode",
        choices=["outbound", "inbound"],
        help="No-PSTN mode. Dispatches localhost room sessions without dialing a number.",
    )
    p.add_argument("--sip-trunk-id", help="Override SIP trunk id")
    p.add_argument("--tenant", help="Tenant id for single-call mode")
    p.add_argument("--mutuelle", default="Harmonie Mutuelle")
    p.add_argument("--dossier-type", default="optique")
    p.add_argument("--patient-name", default="Test Patient")
    p.add_argument("--patient-dob", default="01/01/1985")
    p.add_argument("--nir", default="")
    p.add_argument("--dossier-ref", default="")
    p.add_argument("--montant", type=float, default=100.0)
    p.add_argument("--concurrent", type=int, default=1, help="Number of concurrent outbound calls")
    p.add_argument("--inbound", action="store_true", help="Run inbound monitoring mode")
    p.add_argument("--inbound-number", help="Inbound number to call manually during test")
    p.add_argument(
        "--caller-number",
        default="+33999999999",
        help="Synthetic caller number attached to localhost inbound metadata (not dialed).",
    )
    p.add_argument(
        "--force-ivr",
        action="store_true",
        help="In localhost outbound mode, force IVR navigator path without SIP dialing.",
    )
    p.add_argument(
        "--ivr-path",
        default="1,3",
        help="Comma-separated IVR digits used for localhost IVR simulation.",
    )
    p.add_argument(
        "--target-service",
        default="remboursements optiques",
        help="Target service label for forced IVR navigation mode.",
    )
    p.add_argument("--monitor-seconds", type=int, default=120)
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.localhost_mode:
            asyncio.run(run_localhost(args))
        elif args.inbound:
            asyncio.run(run_inbound(args))
        else:
            asyncio.run(run_outbound(args))
    except KeyboardInterrupt:
        print("Interrupted")
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

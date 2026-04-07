#!/usr/bin/env python3
"""Telnyx + LiveKit outbound SIP trunk setup script.

WHY THIS EXISTS:
The Telnyx MCP server cannot run from this repo's CI/sandbox environment
because the network proxy blocks api.telnyx.com. This script does the same
work locally on your machine where Telnyx is reachable.

WHAT IT DOES:
1. Reads LiveKit and Telnyx credentials from environment variables.
2. Lists existing LiveKit outbound SIP trunks.
3. If a trunk named TRUNK_NAME already exists, prints its ID and runs
   a healthcheck (verifies X-Telnyx-Username is in headers and
   destination_country is set).
4. Otherwise creates one with:
   - address = sip.telnyx.com (Telnyx GeoDNS, anchorsite handles regional routing)
   - destination_country = "FR" (LiveKit region pinning to nearest EU POP)
   - headers includes X-Telnyx-Username (field 9, sent on outbound INVITE)
     NOT headers_to_attributes (field 10, inbound-only mapping direction)
     SECURITY: prevents cross-customer SIP IP collision per Telnyx docs.
   - auth_username + auth_password from env
5. Prints the new trunk ID and the .env line you need to add.

USAGE:
    export LIVEKIT_URL="wss://your-project.livekit.cloud"
    export LIVEKIT_API_KEY="API..."
    export LIVEKIT_API_SECRET="..."
    export TELNYX_USERNAME="your-sip-username"
    export TELNYX_PASSWORD="your-sip-password"
    export TELNYX_FROM_NUMBER="+33XXXXXXXXX"
    python scripts/telnyx_setup.py

OPTIONAL:
    export TELNYX_TRUNK_NAME="telnyx-france-outbound"
    export TELNYX_DESTINATION_COUNTRY="FR"

This script is IDEMPOTENT: re-running it after the trunk exists will detect
the existing trunk and print its ID rather than creating a duplicate.

SOURCES:
- LiveKit Telnyx provider docs: https://docs.livekit.io/telephony/start/providers/telnyx/
- Telnyx LiveKit configuration guide: https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide
- LiveKit region pinning: https://docs.livekit.io/telephony/features/region-pinning/
- Telnyx X-Telnyx-Username security context: cross-customer SIP IP collision warning
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"ERROR: env var {name} is not set", file=sys.stderr)
        sys.exit(1)
    return val


def _optional_env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


async def main() -> int:
    # Lazy import so the script can print a useful error if livekit-api is missing.
    try:
        from livekit.api import (
            LiveKitAPI,
            CreateSIPOutboundTrunkRequest,
            ListSIPOutboundTrunkRequest,
        )
        from livekit.protocol.sip import SIPOutboundTrunkInfo
    except ImportError as exc:
        print(f"ERROR: cannot import livekit-api ({exc}). Install with:", file=sys.stderr)
        print("  pip install livekit-api", file=sys.stderr)
        return 2

    livekit_url = _require_env("LIVEKIT_URL")
    livekit_api_key = _require_env("LIVEKIT_API_KEY")
    livekit_api_secret = _require_env("LIVEKIT_API_SECRET")

    telnyx_username = _require_env("TELNYX_USERNAME")
    telnyx_password = _require_env("TELNYX_PASSWORD")
    from_number = _require_env("TELNYX_FROM_NUMBER")

    trunk_name = _optional_env("TELNYX_TRUNK_NAME", "telnyx-france-outbound")
    destination_country = _optional_env("TELNYX_DESTINATION_COUNTRY", "FR")

    if not from_number.startswith("+"):
        print(
            f"WARNING: TELNYX_FROM_NUMBER ({from_number!r}) does not start with '+'. "
            "E.164 format is required for international routing.",
            file=sys.stderr,
        )

    # Convert ws/wss to http/https for the REST API client.
    api_url = livekit_url.replace("wss://", "https://").replace("ws://", "http://")

    print(f"Connecting to LiveKit at {api_url}")
    lk = LiveKitAPI(api_url, livekit_api_key, livekit_api_secret)

    try:
        # Step 1: list existing outbound trunks (idempotency check)
        print(f"Listing existing outbound trunks to check for '{trunk_name}'...")
        list_resp = await lk.sip.list_sip_outbound_trunk(ListSIPOutboundTrunkRequest())
        existing_trunks = list(list_resp.items)
        print(f"Found {len(existing_trunks)} existing outbound trunk(s)")

        for trunk in existing_trunks:
            if trunk.name == trunk_name:
                print()
                print("=" * 70)
                print("EXISTING TRUNK FOUND - reusing it (no changes made)")
                print("=" * 70)
                print(f"  Trunk ID:           {trunk.sip_trunk_id}")
                print(f"  Name:               {trunk.name}")
                print(f"  Address:            {trunk.address}")
                print(f"  Numbers:            {list(trunk.numbers)}")
                print(f"  Destination:        {trunk.destination_country or '(none)'}")
                print(f"  Headers (INVITE):   {dict(trunk.headers)}")
                print(f"  Headers to attrs:   {dict(trunk.headers_to_attributes)}")
                print()

                # Health check: assert the trunk has what we need
                warnings: list[str] = []
                if not str(trunk.sip_trunk_id).startswith("ST_"):
                    warnings.append(
                        f"Trunk ID {trunk.sip_trunk_id!r} does not start with 'ST_' "
                        "(expected LiveKit outbound trunk format)"
                    )
                if "X-Telnyx-Username" not in dict(trunk.headers):
                    warnings.append(
                        "X-Telnyx-Username is MISSING from trunk.headers. "
                        "This means LiveKit will NOT send the username on the "
                        "outbound INVITE, so Telnyx will challenge every call "
                        "with 407 Proxy Authentication Required, AND there is "
                        "a cross-customer SIP IP collision security risk. "
                        "Delete this trunk and re-run this script to fix."
                    )
                if not trunk.destination_country:
                    warnings.append(
                        "destination_country is empty. LiveKit region pinning "
                        "is disabled. Calls may route via US POPs even for "
                        "French destinations. Re-run with TELNYX_DESTINATION_COUNTRY=FR."
                    )
                if warnings:
                    print("WARNINGS:")
                    for w in warnings:
                        print(f"  - {w}")
                    print()
                else:
                    print("Healthcheck: OK")
                    print()

                print("Add this to your .env file:")
                print(f"  LIVEKIT_SIP_OUTBOUND_TRUNK_ID={trunk.sip_trunk_id}")
                return 0 if not warnings else 4

        # Step 2: create the trunk
        print()
        print(f"No trunk named '{trunk_name}' found. Creating it now...")
        trunk_info = SIPOutboundTrunkInfo(
            name=trunk_name,
            address="sip.telnyx.com",
            numbers=[from_number],
            auth_username=telnyx_username,
            auth_password=telnyx_password,
            destination_country=destination_country,
            # SECURITY: X-Telnyx-Username forces digest auth on every call.
            # Without this, Telnyx may match a SIP IP connection belonging
            # to a DIFFERENT customer if source IPs collide on shared infra.
            #
            # IMPORTANT: use `headers` (field 9), NOT `headers_to_attributes`.
            # - `headers` are sent ON THE OUTBOUND INVITE (LiveKit -> Telnyx).
            # - `headers_to_attributes` maps inbound 200 OK response headers
            #   to LiveKit participant attributes (opposite direction).
            # Source: livekit/protocol/protobufs/livekit_sip.proto,
            # livekit/sip issue #358.
            headers={"X-Telnyx-Username": telnyx_username},
        )
        create_resp = await lk.sip.create_sip_outbound_trunk(
            CreateSIPOutboundTrunkRequest(trunk=trunk_info)
        )
        new_trunk = create_resp

        print()
        print("=" * 70)
        print("TRUNK CREATED SUCCESSFULLY")
        print("=" * 70)
        print(f"  Trunk ID:           {new_trunk.sip_trunk_id}")
        print(f"  Name:               {new_trunk.name}")
        print(f"  Address:            {new_trunk.address}")
        print(f"  Numbers:            {list(new_trunk.numbers)}")
        print(f"  Destination:        {new_trunk.destination_country}")
        print(f"  Headers (INVITE):   {dict(new_trunk.headers)}")
        print()
        print("Add this to your .env file:")
        print(f"  LIVEKIT_SIP_OUTBOUND_TRUNK_ID={new_trunk.sip_trunk_id}")
        print()
        print("Next steps in the Telnyx portal (manual, see runbook):")
        print("  1. Set anchorsite to Frankfurt or Paris (Voice API > Applications)")
        print("  2. Enable G.711U + G.711A codecs on the SIP Connection")
        print("     (Real-Time Communications > SIP Trunking > Inbound > Codecs)")
        print("  3. AVOID G.722 if you use DTMF for IVR navigation")
        print("  4. Attach the Outbound Voice Profile to the SIP Connection")
        print("  5. (Optional) Enable SIP REFER via Telnyx support if you need warm transfers")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    finally:
        await lk.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Setup LiveKit Cloud: create dispatch rule for unified optibot agent.

Reads credentials from .env (never hardcoded).
Uses non-deprecated API methods.

Usage: python scripts/setup_livekit_cloud.py
"""
import asyncio
import json
import os

from dotenv import load_dotenv
load_dotenv()


async def main():
    from livekit import api

    lk_url = os.environ["LIVEKIT_URL"].replace("wss://", "https://").replace("ws://", "http://")
    lk = api.LiveKitAPI(
        url=lk_url,
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    print(f"=== LiveKit Cloud Setup ===")
    print(f"URL: {os.environ['LIVEKIT_URL']}")

    # List existing trunks
    print("\n--- SIP Trunks ---")
    try:
        inbound = await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        for t in inbound.items:
            print(f"  Inbound: {t.sip_trunk_id} - {t.name} - {t.numbers}")
        outbound = await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        for t in outbound.items:
            print(f"  Outbound: {t.sip_trunk_id} - {t.name}")
        if not inbound.items and not outbound.items:
            print("  None — create in LiveKit Cloud dashboard")
    except Exception as e:
        print(f"  Error: {e}")

    # List dispatch rules
    print("\n--- Dispatch Rules ---")
    try:
        rules = await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        for r in rules.items:
            print(f"  {r.sip_dispatch_rule_id}: {r.name}")
        if not rules.items:
            print("  None — creating...")
    except Exception as e:
        print(f"  Error: {e}")

    # Create dispatch rule if none exists
    try:
        rules = await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        has_optibot_rule = any("optibot" in (r.name or "") for r in rules.items)

        if not has_optibot_rule:
            print("\n--- Creating Dispatch Rule ---")
            rule = api.SIPDispatchRule(
                dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="inbound-")
            )
            dispatch = await lk.sip.create_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(
                    dispatch_rule=api.SIPDispatchRuleInfo(
                        rule=rule,
                        name="optibot-unified-rule",
                        room_config=api.RoomConfiguration(
                            agents=[api.RoomAgentDispatch(
                                agent_name="optibot",
                                metadata=json.dumps({"tenant_id": "default", "mode": "inbound"}),
                            )]
                        ),
                    )
                )
            )
            print(f"  Created: {dispatch.sip_dispatch_rule_id}")
        else:
            print("  optibot rule already exists")
    except Exception as e:
        print(f"  Error: {e}")

    # Test connectivity
    print("\n--- Connectivity ---")
    rooms = await lk.room.list_rooms(api.ListRoomsRequest())
    print(f"  Active rooms: {len(rooms.rooms)}")

    await lk.aclose()
    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())

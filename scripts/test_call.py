"""Test script — place a test outbound call via the API.

Usage:
    python scripts/test_call.py --phone +33123456789 --mutuelle "MGEN"
    python scripts/test_call.py --dry-run  # test without actual PSTN call
"""
import argparse
import asyncio
import json
import os
import sys

import httpx


async def main():
    parser = argparse.ArgumentParser(description="Test OptiBot outbound call")
    parser.add_argument("--api-url", default="http://localhost:8080")
    parser.add_argument("--api-key", default=os.getenv("OPTIBOT_API_KEY", ""))
    parser.add_argument("--phone", default="+15005550006")
    parser.add_argument("--tenant-id", default="test-optician")
    parser.add_argument("--mutuelle", default="MGEN")
    parser.add_argument("--patient", default="Jean Dupont")
    parser.add_argument("--dossier-ref", default="BR-2024-TEST")
    parser.add_argument("--montant", type=float, default=150.0)
    parser.add_argument("--dry-run", action="store_true", help="Test API only, no real call")
    args = parser.parse_args()

    print(f"Testing OptiBot API at {args.api_url}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Health check
        print("\n1. Health check...")
        resp = await client.get(f"{args.api_url}/health")
        print(f"   {resp.status_code}: {resp.json()}")

        # Metrics
        print("\n2. Metrics endpoint...")
        resp = await client.get(f"{args.api_url}/metrics")
        lines = resp.text.strip().split("\n")
        print(f"   {resp.status_code}: {len(lines)} metric lines")

        if args.dry_run:
            print("\n3. DRY RUN — skipping actual call dispatch")
            print("   Would call: ", json.dumps({
                "phone": args.phone,
                "tenant_id": args.tenant_id,
                "mutuelle": args.mutuelle,
                "patient_name": args.patient,
            }, indent=2))
            return

        if not args.api_key:
            print("\n3. Missing API key. Use --api-key or set OPTIBOT_API_KEY.")
            sys.exit(2)

        # Dispatch call
        print(f"\n3. Dispatching call to {args.phone} ({args.mutuelle})...")
        resp = await client.post(
            f"{args.api_url}/api/call",
            headers={"Authorization": f"Bearer {args.api_key}"},
            json={
                "phone": args.phone,
                "dossier_id": "test-001",
                "tenant_id": args.tenant_id,
                "patient_name": args.patient,
                "mutuelle": args.mutuelle,
                "dossier_ref": args.dossier_ref,
                "montant": args.montant,
                "dossier_type": "optique",
            },
        )
        print(f"   {resp.status_code}: {resp.json()}")


if __name__ == "__main__":
    asyncio.run(main())

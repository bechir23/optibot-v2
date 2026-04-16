"""Create a new tenant with a fresh API key (Phase 5 Blocker 4).

Usage:
    python scripts/create_tenant.py --id maison-olivier --name "Maison Olivier Opticien"
    python scripts/create_tenant.py --id maison-olivier --name "Maison Olivier" --max-calls 10

Outputs the raw API key ONCE — save it, it cannot be retrieved later.
Only the SHA-256 hash is stored in Supabase.
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from app.api.tenant_auth import hash_api_key
from app.config.settings import Settings
from app.services.supabase_client import SupabaseClient


async def create_tenant(
    tenant_id: str,
    name: str,
    max_calls: int = 5,
    label: str = "prod",
    recording_enabled: bool = False,
    consent_template: str | None = None,
):
    settings = Settings()
    if not settings.supabase_url or not settings.supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env", file=sys.stderr)
        sys.exit(1)

    supabase = SupabaseClient(settings.supabase_url, settings.supabase_key)

    # Check if tenant exists
    existing = await supabase.select("tenants", {"id": tenant_id}, limit=1)
    if existing:
        print(f"ERROR: tenant '{tenant_id}' already exists", file=sys.stderr)
        sys.exit(1)

    # Insert tenant row
    tenant_row = {
        "id": tenant_id,
        "name": name,
        "max_concurrent_calls": max_calls,
        "recording_enabled": recording_enabled,
        "active": True,
    }
    if consent_template:
        tenant_row["consent_disclosure"] = consent_template

    await supabase.insert("tenants", tenant_row)
    print(f"[OK] Tenant '{tenant_id}' created")

    # Generate raw API key — 32 bytes urlsafe, prefixed with 'opti_'
    raw_key = f"opti_{secrets.token_urlsafe(32)}"
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:12]

    await supabase.insert("tenant_api_keys", {
        "tenant_id": tenant_id,
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "label": label,
        "active": True,
    })
    print(f"[OK] API key created (label='{label}')\n")

    print("=" * 72)
    print(" API KEY — SAVE THIS NOW, IT CANNOT BE RETRIEVED LATER")
    print("=" * 72)
    print(f"\n  {raw_key}\n")
    print("=" * 72)
    print(f"\n  Send to customer with instructions:")
    print(f"  curl -H 'Authorization: Bearer {raw_key[:20]}...' \\")
    print(f"       -H 'Content-Type: application/json' \\")
    print(f"       https://api.optibot.example/api/call")
    print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True, help="Tenant ID (stable slug, e.g. 'maison-olivier')")
    p.add_argument("--name", required=True, help="Display name (e.g. 'Maison Olivier Opticien')")
    p.add_argument("--max-calls", type=int, default=5, help="Max concurrent calls")
    p.add_argument("--label", default="prod", help="API key label (prod/staging/etc.)")
    p.add_argument("--recording", action="store_true", help="Enable call recording")
    p.add_argument("--consent", default=None, help="Custom consent template with {tenant_name} placeholder")
    args = p.parse_args()

    asyncio.run(create_tenant(
        args.id, args.name, args.max_calls, args.label, args.recording, args.consent,
    ))


if __name__ == "__main__":
    main()

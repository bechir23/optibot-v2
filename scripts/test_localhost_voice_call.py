"""Initiate a real Twilio voice call into localhost TwiML flow.

This script creates a call via Twilio REST API using your configured callback URL.

Examples:
    python scripts/test_localhost_voice_call.py --to +33600112233 --from-number +33123456789 --voice-url https://abc.ngrok-free.app/twilio/voice
    python scripts/test_localhost_voice_call.py --to +33600112233 --from-number +33123456789 --base-url https://abc.ngrok-free.app --poll-seconds 60
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from urllib.parse import quote_plus
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _normalize_phone(value: str) -> str:
    phone = value.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+330"):
        phone = "+33" + phone[4:]
    return phone


def _validate_e164(name: str, value: str) -> str:
    phone = _normalize_phone(value)
    if not E164_RE.match(phone):
        raise RuntimeError(f"Invalid {name} phone number (expected E.164): {value}")
    return phone


def _build_urls(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.voice_url:
        voice_url = args.voice_url.rstrip("/")
        status_url = args.status_url.rstrip("/") if args.status_url else None
        _validate_callback_urls(
            voice_url=voice_url,
            status_url=status_url,
            explicit_base=args.base_url,
        )
        return voice_url, status_url

    base = args.base_url or os.getenv("PUBLIC_BASE_URL", "").strip()
    if not base:
        raise RuntimeError("Provide --voice-url or --base-url (or set PUBLIC_BASE_URL)")
    base = base.rstrip("/")
    voice_url = f"{base}/twilio/voice"
    status_url = args.status_url.rstrip("/") if args.status_url else f"{base}/twilio/status"
    _validate_callback_urls(
        voice_url=voice_url,
        status_url=status_url,
        explicit_base=base,
    )
    return voice_url, status_url


def _validate_callback_urls(
    *,
    voice_url: str,
    status_url: str | None,
    explicit_base: str | None,
) -> None:
    voice_scheme = urlparse(voice_url).scheme.lower()
    if voice_scheme != "https":
        raise RuntimeError(
            f"Voice URL must be https for Twilio callbacks: {voice_url}"
        )

    if status_url:
        status_scheme = urlparse(status_url).scheme.lower()
        if status_scheme != "https":
            raise RuntimeError(
                f"Status URL must be https for Twilio callbacks: {status_url}"
            )

    env_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit_base and env_base and explicit_base.rstrip("/") != env_base:
        raise RuntimeError(
            "PUBLIC_BASE_URL mismatch. Ensure --base-url and PUBLIC_BASE_URL are exactly the same. "
            f"base={explicit_base.rstrip('/')} env={env_base}"
        )


async def _preflight_callback_urls(
    voice_url: str,
    status_url: str | None,
    skip_preflight: bool,
) -> None:
    if skip_preflight:
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        voice_resp = await client.get(voice_url)
        if voice_resp.status_code >= 400:
            raise RuntimeError(
                f"Voice webhook preflight failed [{voice_resp.status_code}] at {voice_url}"
            )

        if status_url:
            status_resp = await client.get(status_url)
            if status_resp.status_code >= 400:
                raise RuntimeError(
                    f"Status webhook preflight failed [{status_resp.status_code}] at {status_url}"
                )


async def create_call(args: argparse.Namespace) -> str:
    sid = _required_env("TWILIO_ACCOUNT_SID")
    token = _required_env("TWILIO_AUTH_TOKEN")

    to_phone = _validate_e164("to", args.to)
    from_phone = _validate_e164("from", args.from_number)
    voice_url, status_url = _build_urls(args)
    await _preflight_callback_urls(
        voice_url=voice_url,
        status_url=status_url,
        skip_preflight=args.skip_preflight,
    )

    body_parts = [
        f"To={quote_plus(to_phone)}",
        f"From={quote_plus(from_phone)}",
        f"Url={quote_plus(voice_url)}",
        "Method=POST",
    ]
    if status_url:
        body_parts.extend(
            [
                f"StatusCallback={quote_plus(status_url)}",
                "StatusCallbackMethod=POST",
                "StatusCallbackEvent=initiated",
                "StatusCallbackEvent=ringing",
                "StatusCallbackEvent=answered",
                "StatusCallbackEvent=completed",
            ]
        )

    if args.machine_detection:
        body_parts.append(f"MachineDetection={quote_plus(args.machine_detection)}")

    body = "&".join(body_parts)

    if args.dry_run:
        print("DRY RUN")
        print(f"To={to_phone}")
        print(f"From={from_phone}")
        print(f"Voice URL={voice_url}")
        print(f"Status URL={status_url or '<none>'}")
        print(f"MachineDetection={args.machine_detection or '<none>'}")
        return ""

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
    async with httpx.AsyncClient(timeout=30.0, auth=(sid, token)) as client:
        resp = await client.post(
            url,
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code >= 300:
            raise RuntimeError(f"Twilio call create failed [{resp.status_code}]: {resp.text}")

        data = resp.json()
        call_sid = data.get("sid", "")
        status = data.get("status", "")
        print(f"Call created: sid={call_sid} status={status}")
        return call_sid


async def poll_call(call_sid: str, poll_seconds: int) -> None:
    if not call_sid:
        return

    sid = _required_env("TWILIO_ACCOUNT_SID")
    token = _required_env("TWILIO_AUTH_TOKEN")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json"

    elapsed = 0
    async with httpx.AsyncClient(timeout=20.0, auth=(sid, token)) as client:
        while elapsed < poll_seconds:
            resp = await client.get(url)
            if resp.status_code >= 300:
                print(f"Poll failed [{resp.status_code}]: {resp.text}")
                break

            data = resp.json()
            status = data.get("status", "")
            duration = data.get("duration", "")
            print(f"Call status={status} duration={duration}")

            if status in {"completed", "failed", "busy", "no-answer", "canceled"}:
                break

            await asyncio.sleep(3)
            elapsed += 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create a real Twilio call to localhost TwiML")
    p.add_argument("--to", required=True, help="Destination number in E.164")
    p.add_argument("--from-number", required=True, help="Twilio owned number in E.164")
    p.add_argument("--voice-url", help="Full voice webhook URL")
    p.add_argument("--base-url", help="Base public URL used to build /twilio/voice and /twilio/status")
    p.add_argument("--status-url", help="Full status callback URL")
    p.add_argument("--machine-detection", choices=["Enable", "DetectMessageEnd"], help="Twilio AMD mode")
    p.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip callback URL reachability checks before call creation.",
    )
    p.add_argument("--poll-seconds", type=int, default=60)
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        call_sid = asyncio.run(create_call(args))
        if not args.dry_run:
            asyncio.run(poll_call(call_sid, args.poll_seconds))
    except KeyboardInterrupt:
        print("Interrupted")
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

"""Localhost TwiML webhook server for real voice and audio testing.

Run:
    python scripts/localhost_twiml_server.py --port 8088

Then expose with a tunnel and configure provider callback to:
    https://<your-tunnel-domain>/twilio/voice

Optional environment variables:
    PUBLIC_BASE_URL=https://<your-tunnel-domain>
    TWIML_LOG_FILE=data/twilio_webhook_events.jsonl
    TWIML_AUDIO_FILE=test_audio.wav
    TWIML_ENABLE_PLAY=1
    TWIML_SAY_TEXT=Hello from localhost
    TWIML_GATHER_PROMPT=Please say your name after the beep.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
import uvicorn


app = FastAPI(title="Localhost TwiML Server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("twiml-localhost")


def _log_path() -> Path:
    path = Path(os.getenv("TWIML_LOG_FILE", "data/twilio_webhook_events.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _audio_path() -> Path:
    return Path(os.getenv("TWIML_AUDIO_FILE", "test_audio.wav"))


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _append_event(route: str, payload: dict) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "route": route,
        "payload": payload,
    }
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _request_payload(request: Request, raw: bytes | None = None) -> dict:
    if request.method == "GET":
        return dict(request.query_params)
    body = raw if raw is not None else b""
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {k: (v[0] if len(v) == 1 else v) for k, v in parsed.items()}


def _public_base_url(request: Request) -> str:
    explicit = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}".rstrip("/")


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name, "1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/twilio/last")
async def twilio_last() -> dict:
    path = _log_path()
    if not path.exists():
        return {"events": []}

    lines = path.read_text(encoding="utf-8").splitlines()
    tail = lines[-30:]
    events = [json.loads(line) for line in tail if line.strip()]
    return {"events": events}


@app.get("/audio/test.wav")
async def audio_test() -> FileResponse:
    wav = _audio_path()
    if not wav.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Audio file not found: {wav}. Set TWIML_AUDIO_FILE or place test_audio.wav in repo root.",
        )
    return FileResponse(path=str(wav), media_type="audio/wav", filename=wav.name)


@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request) -> Response:
    raw = await request.body() if request.method == "POST" else None
    payload = _request_payload(request, raw)

    _append_event("/twilio/voice", payload)
    logger.info("Twilio voice webhook received: method=%s keys=%s", request.method, sorted(payload.keys()))

    base = _public_base_url(request)
    say_text = os.getenv(
        "TWIML_SAY_TEXT",
        "Hello. This is a localhost TwiML test. Your webhook is working.",
    )
    gather_prompt = os.getenv(
        "TWIML_GATHER_PROMPT",
        "Please say your full name after the tone.",
    )
    fallback_text = os.getenv(
        "TWIML_FALLBACK_TEXT",
        "No speech detected. Goodbye.",
    )

    play_xml = ""
    if _env_bool("TWIML_ENABLE_PLAY", default=True):
        play_xml = f"<Play>{_xml_escape(base)}/audio/test.wav</Play>"

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="alice">{_xml_escape(say_text)}</Say>'
        "<Pause length=\"1\"/>"
        f'<Gather input="speech dtmf" action="{_xml_escape(base)}/twilio/gather" method="POST" timeout="5" speechTimeout="auto">'
        f'<Say voice="alice">{_xml_escape(gather_prompt)}</Say>'
        f"{play_xml}"
        "</Gather>"
        f'<Say voice="alice">{_xml_escape(fallback_text)}</Say>'
        "<Hangup/>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@app.api_route("/twilio/gather", methods=["GET", "POST"])
async def twilio_gather(request: Request) -> Response:
    raw = await request.body() if request.method == "POST" else None
    payload = _request_payload(request, raw)

    _append_event("/twilio/gather", payload)
    speech_result = str(payload.get("SpeechResult", "")).strip()
    digits = str(payload.get("Digits", "")).strip()
    logger.info(
        "Twilio gather callback: speech=%s digits=%s confidence=%s",
        speech_result,
        digits,
        payload.get("Confidence", ""),
    )

    if speech_result:
        ack = f"I heard: {speech_result}. Thank you."
    elif digits:
        ack = f"I received digits: {digits}. Thank you."
    else:
        ack = "No input received."

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="alice">{_xml_escape(ack)}</Say>'
        "<Hangup/>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@app.api_route("/twilio/status", methods=["GET", "POST"])
async def twilio_status(request: Request) -> dict[str, str]:
    raw = await request.body() if request.method == "POST" else None
    payload = _request_payload(request, raw)

    _append_event("/twilio/status", payload)
    logger.info("Twilio status callback received: status=%s", payload.get("CallStatus", ""))
    return {"ok": "true"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run localhost TwiML webhook server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

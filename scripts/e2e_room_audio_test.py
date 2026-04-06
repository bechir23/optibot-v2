"""True E2E test: audio -> LiveKit room -> agent STT -> LLM -> TTS -> capture.

This test publishes real audio frames into a LiveKit Cloud room.
The agent's Deepgram STT processes the audio, LLM generates a response,
Cartesia TTS speaks it back, and we capture the agent's audio output.

NO text injection. The full pipeline runs exactly as in production.

Usage:
    python scripts/e2e_room_audio_test.py
    python scripts/e2e_room_audio_test.py --scenario hold
    python scripts/e2e_room_audio_test.py --scenario navigation
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import struct
import time
import wave

import httpx
from dotenv import load_dotenv

load_dotenv()

SCENARIOS = {
    "outbound": [
        "Bonjour, Harmonie Mutuelle, service remboursements, que puis-je faire pour vous?",
        "C'est pour quel patient?",
        "Oui je vois le dossier Dupont. Le remboursement est en cours, comptez quinze jours.",
    ],
    "hold": [
        "Bonjour, MGEN.",
        "Veuillez patienter un instant.",
        "Désolé, je reprends. Le dossier est traité.",
    ],
    "navigation": [
        "Bonjour, vous êtes sur le serveur vocal Harmonie Mutuelle. Pour les remboursements, tapez 1.",
        "Veuillez patienter, je vous transfère au service remboursements optiques.",
        "Service remboursements optiques bonjour, je peux avoir la référence du dossier?",
    ],
}

AGENT_META = {
    "outbound": {
        "tenant_id": "e2e-room-test",
        "dossier": {
            "mutuelle": "Harmonie Mutuelle",
            "patient_name": "Jean Dupont",
            "dossier_ref": "BRD-E2E-001",
            "montant": 779.91,
            "dossier_type": "optique",
        },
    },
    "hold": {
        "tenant_id": "e2e-hold-test",
        "dossier": {
            "mutuelle": "MGEN",
            "patient_name": "Marie Martin",
            "dossier_ref": "BRD-HOLD-E2E",
            "montant": 250.0,
            "dossier_type": "optique",
        },
    },
    "navigation": {
        "tenant_id": "e2e-navigation-test",
        "local_loopback": True,
        "force_ivr": True,
        "target_service": "remboursements optiques",
        "known_ivr_tree": {
            "path_to_reimbursement": ["1", "3"],
            "notes": "E2E navigation simulation",
        },
        "dossier": {
            "mutuelle": "Harmonie Mutuelle",
            "patient_name": "Jean Dupont",
            "dossier_ref": "BRD-NAV-E2E-001",
            "montant": 779.91,
            "dossier_type": "optique",
        },
    },
}


async def generate_caller_audio(text: str) -> bytes:
    """Generate 48kHz mono PCM via Cartesia."""
    key = os.environ["CARTESIA_API_KEY"]
    voice = os.environ.get("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")

    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={"X-API-Key": key, "Cartesia-Version": "2024-06-10", "Content-Type": "application/json"},
            json={
                "model_id": "sonic-3",
                "transcript": text,
                "voice": {"mode": "id", "id": voice},
                "language": "fr",
                "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 48000},
            },
        )
        resp.raise_for_status()
        return resp.content


def pcm_to_wav(pcm: bytes, sr: int = 48000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


async def run_room_test(scenario: str):
    from livekit import api, rtc

    lk_url = os.environ["LIVEKIT_URL"]
    lk_http = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    lk_key = os.environ["LIVEKIT_API_KEY"]
    lk_secret = os.environ["LIVEKIT_API_SECRET"]

    turns = SCENARIOS[scenario]
    meta = AGENT_META[scenario]
    room_name = f"e2e-room-{scenario}-{int(time.time()) % 100000}"

    print(f"\n{'='*60}")
    print(f"TRUE E2E ROOM AUDIO TEST: {scenario}")
    print(f"Room: {room_name}")
    print(f"{'='*60}")

    # Step 1: Dispatch agent to room
    lk_api = api.LiveKitAPI(url=lk_http, api_key=lk_key, api_secret=lk_secret)
    dispatch = await lk_api.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=os.environ.get("AGENT_NAME", "optibot"),
            room=room_name,
            metadata=json.dumps(meta),
        )
    )
    print(f"\n  Agent dispatched: {dispatch.id}")

    # Step 2: Generate participant token
    token = (
        api.AccessToken(api_key=lk_key, api_secret=lk_secret)
        .with_identity("e2e-caller")
        .with_name("E2E Caller")
        .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True))
        .to_jwt()
    )

    # Step 3: Connect to room as participant
    room = rtc.Room()
    agent_audio_chunks: list[bytes] = []
    agent_speaking = False
    transcripts: list[str] = []

    @room.on("track_subscribed")
    def on_track(track: rtc.Track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            stream = rtc.AudioStream(track)

            async def collect_audio():
                async for event in stream:
                    frame = event.frame if hasattr(event, 'frame') else event
                    if hasattr(frame, 'data'):
                        agent_audio_chunks.append(bytes(frame.data))

            asyncio.ensure_future(collect_audio())
            print(f"  Subscribed to agent audio from {participant.identity}")

    @room.on("transcription_received")
    def on_transcript(segments, participant, publication):
        for seg in segments:
            text = seg.text if hasattr(seg, 'text') else str(seg)
            if text.strip():
                transcripts.append(text)
                print(f"  [Agent says] {text[:80]}")

    @room.on("data_received")
    def on_data(data):
        try:
            raw = data.data if hasattr(data, 'data') else data
            if isinstance(raw, bytes):
                msg = json.loads(raw.decode())
            else:
                msg = json.loads(str(raw))
            text = msg.get("text", "")
            if text:
                transcripts.append(text)
                print(f"  [Data] {text[:80]}")
        except Exception:
            pass

    print(f"  Connecting to room...")
    await room.connect(lk_url, token)
    print(f"  Connected as e2e-caller")

    # Wait for agent to join
    await asyncio.sleep(3)

    # Check participants
    participants = list(room.remote_participants.values())
    print(f"  Remote participants: {[p.identity for p in participants]}")

    # Step 4: Create audio source and publish
    audio_source = rtc.AudioSource(sample_rate=48000, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("caller-mic", audio_source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await room.local_participant.publish_track(track, options)
    print(f"  Published audio track (48kHz mono)")

    # Step 5: For each turn, generate audio and push frames
    os.makedirs("test_audio", exist_ok=True)

    for i, text in enumerate(turns):
        print(f"\n  --- Turn {i+1} ---")
        print(f"  Generating: \"{text[:60]}\"")

        t0 = time.monotonic()
        pcm = await generate_caller_audio(text)
        tts_ms = (time.monotonic() - t0) * 1000
        duration_s = len(pcm) / (48000 * 2)
        print(f"  TTS: {tts_ms:.0f}ms, {duration_s:.1f}s audio")

        # Save audio
        wav_path = f"test_audio/e2e_{scenario}_turn{i+1}.wav"
        with open(wav_path, "wb") as f:
            f.write(pcm_to_wav(pcm))
        print(f"  Saved: {wav_path}")

        # Push audio frames into room (20ms chunks at 48kHz = 960 samples)
        samples_per_frame = 960
        bytes_per_frame = samples_per_frame * 2  # 16-bit
        num_frames = len(pcm) // bytes_per_frame

        print(f"  Publishing {num_frames} audio frames...")
        for frame_idx in range(num_frames):
            start = frame_idx * bytes_per_frame
            chunk = pcm[start:start + bytes_per_frame]

            frame = rtc.AudioFrame(
                data=chunk,
                sample_rate=48000,
                num_channels=1,
                samples_per_channel=samples_per_frame,
            )
            await audio_source.capture_frame(frame)

            # Real-time pacing: 20ms per frame
            await asyncio.sleep(0.02)

        print(f"  Audio published. Waiting for agent STT+LLM+TTS pipeline...")

        # Wait for full pipeline: VAD(~1s) + STT(~2s) + LLM(~3s) + TTS(~2s) = ~8s minimum
        await asyncio.sleep(12)

        # Check if we got agent audio back
        agent_bytes = sum(len(c) for c in agent_audio_chunks)
        print(f"  Agent audio received: {agent_bytes} bytes")

    # Step 6: Final wait and cleanup
    print(f"\n  Waiting for final agent response...")
    await asyncio.sleep(10)

    total_agent_audio = sum(len(c) for c in agent_audio_chunks)
    print(f"\n  Total agent audio: {total_agent_audio} bytes")
    print(f"  Transcripts captured: {len(transcripts)}")
    for t in transcripts:
        print(f"    \"{t[:80]}\"")

    # Save agent audio if any
    if agent_audio_chunks:
        agent_pcm = b"".join(agent_audio_chunks)
        with open(f"test_audio/e2e_{scenario}_agent_response.wav", "wb") as f:
            f.write(pcm_to_wav(agent_pcm))
        print(f"  Agent audio saved: test_audio/e2e_{scenario}_agent_response.wav")

    await room.disconnect()
    await lk_api.aclose()

    # Results
    print(f"\n{'='*60}")
    print(f"RESULTS: {scenario}")
    print(f"{'='*60}")
    print(f"  Turns played: {len(turns)}")
    print(f"  Agent audio received: {'YES' if total_agent_audio > 0 else 'NO'} ({total_agent_audio} bytes)")
    print(f"  Transcripts: {len(transcripts)}")
    has_agent_audio = total_agent_audio > 1000
    print(f"  E2E AUDIO PATH: {'PASS' if has_agent_audio else 'FAIL'}")

    return has_agent_audio


def main():
    import sys
    parser = argparse.ArgumentParser(description="True E2E room audio test")
    parser.add_argument("--scenario", default="outbound", choices=list(SCENARIOS.keys()))
    args = parser.parse_args()

    result = asyncio.run(run_room_test(args.scenario))
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()

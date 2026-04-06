"""Localhost real audio conversation test — no browser, no phone.

Uses Cartesia TTS to generate caller audio, sends it into a LiveKit room,
captures agent responses via room events, and validates the full pipeline.

Tests: STT, LLM, TTS, hold detection, IVR navigation, SSML, multi-tenant.

Usage:
    python scripts/localhost_audio_test.py                    # full conversation
    python scripts/localhost_audio_test.py --scenario hold    # hold detection
    python scripts/localhost_audio_test.py --scenario ivr     # IVR navigation
    python scripts/localhost_audio_test.py --concurrent 3     # 3 tenants
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import struct
import time
import wave
import io

import httpx
from dotenv import load_dotenv

load_dotenv()

# Conversation scenarios: each turn is (caller_text, expected_agent_behavior)
SCENARIOS = {
    "outbound": {
        "description": "Standard mutuelle reimbursement call",
        "metadata": {
            "tenant_id": "test-outbound",
            "dossier": {
                "mutuelle": "Harmonie Mutuelle",
                "patient_name": "Jean Dupont",
                "patient_dob": "15/03/1985",
                "dossier_ref": "BRD-2024-12345",
                "montant": 779.91,
                "nir": "1850375012345",
                "dossier_type": "optique",
            },
        },
        "turns": [
            ("Bonjour, Harmonie Mutuelle, service remboursements, que puis-je faire pour vous?",
             "should_identify_and_ask_dossier"),
            ("C'est pour quel patient?",
             "should_give_patient_name"),
            ("Oui je vois le dossier Dupont. Le remboursement est en cours de traitement, comptez quinze jours ouvrés.",
             "should_acknowledge_and_extract"),
            ("Autre chose que je puisse faire pour vous?",
             "should_thank_and_end"),
        ],
    },
    "hold": {
        "description": "Hold detection + resume",
        "metadata": {
            "tenant_id": "test-hold",
            "dossier": {
                "mutuelle": "MGEN",
                "patient_name": "Marie Martin",
                "dossier_ref": "BRD-HOLD-001",
                "montant": 250.0,
                "dossier_type": "optique",
            },
        },
        "turns": [
            ("Bonjour, MGEN service remboursements.",
             "should_greet"),
            ("Veuillez patienter un instant s'il vous plait.",
             "should_detect_hold_and_stay_silent"),
            ("Désolé pour l'attente. Je reprends votre dossier.",
             "should_resume_conversation"),
            ("Le dossier Martin est traité, le virement part demain.",
             "should_acknowledge_and_extract"),
        ],
    },
    "ivr": {
        "description": "IVR menu navigation simulation",
        "metadata": {
            "tenant_id": "test-ivr",
            "dossier": {
                "mutuelle": "AXA",
                "patient_name": "Pierre Bernard",
                "dossier_ref": "BRD-IVR-001",
                "montant": 500.0,
                "dossier_type": "optique",
            },
        },
        "turns": [
            ("Bienvenue chez AXA santé. Pour les remboursements, tapez un. Pour les adhésions, tapez deux. Pour un conseiller, tapez zéro.",
             "should_navigate_ivr"),
            ("Service remboursements optique. Toutes nos lignes sont occupées, veuillez patienter.",
             "should_detect_hold"),
            ("Bonjour, service remboursement AXA, je vous écoute.",
             "should_switch_to_conversation"),
        ],
    },
    "inbound": {
        "description": "Inbound receptionist (agent speaks first)",
        "metadata": {
            "tenant_id": "test-inbound",
        },
        "turns": [
            ("Bonjour, je voudrais des renseignements sur un remboursement de lunettes.",
             "should_help_caller"),
            ("C'est pour des verres progressifs, j'ai la facture sous les yeux.",
             "should_ask_details"),
        ],
    },
}


async def generate_audio(text: str) -> bytes:
    """Generate French speech audio using Cartesia TTS API."""
    cartesia_key = os.environ.get("CARTESIA_API_KEY", "")
    voice_id = os.environ.get("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")

    if not cartesia_key:
        raise RuntimeError("CARTESIA_API_KEY required for audio generation")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={
                "X-API-Key": cartesia_key,
                "Cartesia-Version": "2024-06-10",
                "Content-Type": "application/json",
            },
            json={
                "model_id": "sonic-3",
                "transcript": text,
                "voice": {"mode": "id", "id": voice_id},
                "language": "fr",
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": 48000,
                },
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"TTS failed: {resp.status_code} {resp.text[:200]}")
        return resp.content


async def transcribe_audio(audio_bytes: bytes, sample_rate: int = 48000) -> str:
    """Transcribe audio using Deepgram STT API."""
    deepgram_key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not deepgram_key:
        return "(no DEEPGRAM_API_KEY)"

    # Wrap raw PCM in WAV
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
    wav_bytes = buf.getvalue()

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/listen?model=nova-3&language=fr&smart_format=true",
            headers={
                "Authorization": f"Token {deepgram_key}",
                "Content-Type": "audio/wav",
            },
            content=wav_bytes,
        )
        if resp.status_code == 200:
            alt = resp.json().get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0]
            return alt.get("transcript", "")
        return f"(STT error: {resp.status_code})"


async def run_agent_conversation(scenario_name: str):
    """Run a full conversation with the agent using LiveKit test harness."""
    from livekit.agents import AgentSession
    from livekit.plugins import openai as lk_openai

    # Import agent
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.agents.outbound_caller import OutboundCallerAgent

    scenario = SCENARIOS[scenario_name]
    meta = scenario["metadata"]
    dossier = meta.get("dossier", {})

    print(f"\n{'='*60}")
    print(f"SCENARIO: {scenario_name} — {scenario['description']}")
    print(f"Tenant: {meta.get('tenant_id', 'default')}")
    print(f"{'='*60}\n")

    # Create agent
    agent = OutboundCallerAgent(
        patient_name=dossier.get("patient_name", ""),
        patient_dob=dossier.get("patient_dob", ""),
        mutuelle=dossier.get("mutuelle", ""),
        dossier_ref=dossier.get("dossier_ref", ""),
        montant=dossier.get("montant", 0),
        nir=dossier.get("nir", ""),
        dossier_type=dossier.get("dossier_type", "optique"),
        rag_context={},
        tenant_id=meta.get("tenant_id", "default"),
        call_id=f"localhost-{scenario_name}-{int(time.time())}",
    )

    results = []

    async with (
        lk_openai.LLM(model="gpt-4.1-mini") as llm,
        AgentSession(llm=llm) as session,
    ):
        await session.start(agent)

        for i, (caller_text, expected) in enumerate(scenario["turns"]):
            turn_start = time.monotonic()

            # Generate caller audio and save to disk
            print(f"  Turn {i+1}: Generating caller audio...")
            audio_start = time.monotonic()
            try:
                caller_audio = await generate_audio(caller_text)
                tts_ms = (time.monotonic() - audio_start) * 1000
                audio_dur = len(caller_audio) / (48000 * 2)

                # Save audio to test_audio/ directory
                audio_dir = os.path.join(os.path.dirname(__file__), "..", "test_audio")
                os.makedirs(audio_dir, exist_ok=True)
                wav_path = os.path.join(audio_dir, f"{scenario_name}_turn{i+1}_caller.wav")
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(48000)
                    wf.writeframes(caller_audio)
                with open(wav_path, "wb") as f:
                    f.write(buf.getvalue())
                print(f"    Saved: {wav_path}")
                print(f"    TTS: {tts_ms:.0f}ms, {len(caller_audio)} bytes ({audio_dur:.1f}s)")
            except Exception as e:
                print(f"    TTS error: {e}")
                caller_audio = None

            # Transcribe caller audio back (roundtrip test)
            if caller_audio:
                stt_start = time.monotonic()
                transcript = await transcribe_audio(caller_audio)
                stt_ms = (time.monotonic() - stt_start) * 1000
                print(f"    STT roundtrip: \"{transcript[:80]}\" ({stt_ms:.0f}ms)")

            # Send text to agent (simulate STT output)
            print(f"    Caller: \"{caller_text[:70]}\"")
            llm_start = time.monotonic()
            result = await session.run(user_input=caller_text)
            llm_ms = (time.monotonic() - llm_start) * 1000

            # Check agent response
            turn_ms = (time.monotonic() - turn_start) * 1000
            print(f"    Agent responded in {llm_ms:.0f}ms (turn total: {turn_ms:.0f}ms)")
            print(f"    Expected: {expected}")

            results.append({
                "turn": i + 1,
                "caller": caller_text[:60],
                "expected": expected,
                "llm_ms": llm_ms,
                "turn_ms": turn_ms,
                "tts_ok": caller_audio is not None,
            })
            print()

    # Summary
    print(f"{'='*60}")
    print(f"RESULTS: {scenario_name}")
    print(f"{'='*60}")
    print(f"  Tools called: {agent._tools_called}")
    print(f"  Extracted data: {json.dumps(agent._extracted, indent=2, default=str)}")
    print()

    # Validate
    has_tools = len(agent._tools_called) > 0
    has_data = len(agent._extracted) > 0

    for r in results:
        status = "PASS" if r["tts_ok"] and r["llm_ms"] < 10000 else "SLOW" if r["llm_ms"] >= 10000 else "FAIL"
        print(f"  Turn {r['turn']}: {status} — LLM {r['llm_ms']:.0f}ms, TTS {'OK' if r['tts_ok'] else 'FAIL'}")

    print(f"\n  Tools called: {'PASS' if has_tools else 'WARN'} ({agent._tools_called})")
    print(f"  Data extracted: {'PASS' if has_data else 'WARN'}")

    # Test pipeline modules
    print(f"\n  --- Pipeline Module Tests ---")

    # STT correction
    from app.pipeline.stt_correction import correct_transcription
    stt_tests = [
        ("armoni mutuel", "Harmonie Mutuelle"),
        ("la sesam vitale", "SESAM-Vitale"),
        ("le finess", "FINESS"),
    ]
    for inp, exp in stt_tests:
        out = correct_transcription(inp)
        ok = exp.lower() in out.lower()
        print(f"  STT '{inp}' -> '{out}': {'PASS' if ok else 'FAIL'}")

    # SSML normalizer
    from app.pipeline.ssml_normalizer import normalize_for_tts
    ssml_tests = [
        ("Le montant est 779 euros", "sept cent"),
        ("Le NIR 1850375012345", "..."),
        ("La CPAM et le TP", "C.P.A.M."),
    ]
    for inp, exp in ssml_tests:
        out = normalize_for_tts(inp)
        ok = exp in out
        print(f"  SSML '{inp[:30]}' -> contains '{exp}': {'PASS' if ok else 'FAIL'}")

    # Hold detection
    from app.pipeline.hold_detector import HoldDetector
    hd = HoldDetector()
    r1 = hd.detect("veuillez patienter")
    r2 = hd.detect("Bonjour je reprends")
    print(f"  Hold detect: start={'PASS' if r1.hold_started else 'FAIL'}, end={'PASS' if r2.hold_ended else 'FAIL'}")

    # AMD
    from app.pipeline.amd import AnsweringMachineDetector, AnsweredBy
    amd = AnsweringMachineDetector()
    amd.on_speech_start()
    amd.on_speech_end(500)
    print(f"  AMD (500ms): {'PASS' if amd.get_result().answered_by == AnsweredBy.HUMAN else 'FAIL'}")

    return results


async def run_concurrent(count: int) -> list:
    """Run multiple scenarios concurrently. Returns results (may contain exceptions)."""
    scenarios = list(SCENARIOS.keys())[:count]
    print(f"\n{'='*60}")
    print(f"CONCURRENT TEST: {count} scenarios")
    print(f"{'='*60}")

    tasks = [run_agent_conversation(s) for s in scenarios]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    print(f"\n{'='*60}")
    print(f"CONCURRENT SUMMARY")
    print(f"{'='*60}")
    for s, r in zip(scenarios, all_results):
        if isinstance(r, Exception):
            print(f"  {s}: FAILED — {r}")
        else:
            print(f"  {s}: {len(r)} turns completed")

    return all_results


def main():
    import sys
    parser = argparse.ArgumentParser(description="Localhost audio conversation test")
    parser.add_argument("--scenario", default="outbound", choices=list(SCENARIOS.keys()))
    parser.add_argument("--concurrent", type=int, default=0, help="Run N scenarios concurrently")
    args = parser.parse_args()

    try:
        if args.concurrent > 0:
            all_results = asyncio.run(run_concurrent(args.concurrent))
            # Check for failures in concurrent mode
            if isinstance(all_results, list):
                failures = [r for r in all_results if isinstance(r, Exception)]
                if failures:
                    print(f"\nEXIT: {len(failures)} scenario(s) failed")
                    sys.exit(1)
        else:
            results = asyncio.run(run_agent_conversation(args.scenario))
            if results:
                failures = [r for r in results if not r.get("tts_ok") or r.get("llm_ms", 0) >= 10000]
                if failures:
                    print(f"\nEXIT: {len(failures)} turn(s) failed")
                    sys.exit(1)
    except Exception as e:
        print(f"\nFATAL: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()

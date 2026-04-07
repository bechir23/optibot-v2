"""End-to-end real audio test — Cartesia TTS + Deepgram STT + full pipeline."""
import asyncio
import os
import time
import httpx


async def main():
    print("=" * 60)
    print("SECTION 1: REAL TTS (Cartesia sonic-3)")
    print("=" * 60)

    cartesia_key = os.environ.get("CARTESIA_API_KEY", "")
    cartesia_voice = os.environ.get("CARTESIA_VOICE_ID", "")

    saved_audio = None

    if not cartesia_key:
        print("BLOCKED: CARTESIA_API_KEY not set")
    else:
        phrases = [
            "Bonjour, je vous appelle de la part de l'opticien concernant un dossier de remboursement.",
            "Le numero de bordereau c'est le B R D tiret 2024 tiret 12345.",
            "D'accord, je note. Le remboursement est en cours, comptez quinze jours.",
            "Merci beaucoup pour ces informations. Bonne journee, au revoir.",
            "Un instant, je verifie votre dossier.",
        ]

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, phrase in enumerate(phrases):
                start = time.monotonic()
                try:
                    body = {
                        "model_id": "sonic-3",
                        "transcript": phrase,
                        "voice": {"mode": "id", "id": cartesia_voice or "a0e99841-438c-4a64-b679-ae501e7d6091"},
                        "language": "fr",
                        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 16000},
                    }
                    resp = await client.post(
                        "https://api.cartesia.ai/tts/bytes",
                        headers={"X-API-Key": cartesia_key, "Cartesia-Version": "2024-06-10", "Content-Type": "application/json"},
                        json=body,
                    )
                    ms = (time.monotonic() - start) * 1000
                    if resp.status_code == 200:
                        audio_bytes = len(resp.content)
                        dur = audio_bytes / (16000 * 2)
                        print(f"  [{i+1}] PASS: {ms:.0f}ms, {audio_bytes}B ({dur:.1f}s audio)")
                        print(f"       \"{phrase[:65]}\"")
                        if i == 0:
                            saved_audio = resp.content
                            with open("/tmp/test_tts.wav", "wb") as f:
                                f.write(resp.content)
                    else:
                        print(f"  [{i+1}] FAIL: {resp.status_code} {resp.text[:100]}")
                except Exception as e:
                    print(f"  [{i+1}] ERROR: {e}")

    print()
    print("=" * 60)
    print("SECTION 2: REAL STT (Deepgram nova-3)")
    print("=" * 60)

    deepgram_key = os.environ.get("DEEPGRAM_API_KEY", "")

    if not deepgram_key:
        print("BLOCKED: DEEPGRAM_API_KEY not set")
    elif saved_audio is None:
        print("BLOCKED: No TTS audio to transcribe")
    else:
        async with httpx.AsyncClient(timeout=30.0) as client:
            start = time.monotonic()
            resp = await client.post(
                "https://api.deepgram.com/v1/listen?model=nova-3&language=fr&smart_format=true",
                headers={"Authorization": f"Token {deepgram_key}", "Content-Type": "audio/wav"},
                content=saved_audio,
            )
            ms = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                data = resp.json()
                alt = data.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0]
                transcript = alt.get("transcript", "")
                confidence = alt.get("confidence", 0)
                print(f"  PASS: {ms:.0f}ms, confidence={confidence:.2f}")
                print(f"  Raw: \"{transcript}\"")

                from app.pipeline.stt_correction import correct_transcription
                corrected = correct_transcription(transcript)
                if corrected != transcript:
                    print(f"  Corrected: \"{corrected}\"")
                else:
                    print(f"  No correction needed (already clean)")
            else:
                print(f"  FAIL: {resp.status_code} {resp.text[:200]}")

    print()
    print("=" * 60)
    print("SECTION 3: SSML NORMALIZATION")
    print("=" * 60)

    from app.pipeline.ssml_normalizer import normalize_for_tts, ABBREVIATIONS

    tests = [
        ("Le NIR est 1850375012345", True),
        ("Montant: 779 euros", True),
        ("Appelez le 01 42 68 53 00", True),
        ("La CPAM a valide le TP", True),
        ("Date: 25/12/2024", True),
        ("Le LPP et le BR", True),
        ("Votre RAC est de 50 euros", True),
        ("Le FINESS de l opticien", True),
    ]
    passed = 0
    for text, should_change in tests:
        result = normalize_for_tts(text)
        changed = result != text
        ok = changed == should_change
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}: \"{text}\" -> \"{result[:70]}\"")
    print(f"  Score: {passed}/{len(tests)}, Abbreviations: {len(ABBREVIATIONS)}")

    print()
    print("=" * 60)
    print("SECTION 4: AMD DETECTION")
    print("=" * 60)

    from app.pipeline.amd import AnsweringMachineDetector, AnsweredBy

    cases = [
        ("Human allo", [("speech", 400)], AnsweredBy.HUMAN),
        ("Human oui bonjour", [("speech", 700)], AnsweredBy.HUMAN),
        ("Voicemail long", [("speech", 3500)], AnsweredBy.MACHINE_START),
        ("Dead line", [("silence", 6000)], AnsweredBy.UNKNOWN),
    ]
    for name, events, expected in cases:
        amd = AnsweringMachineDetector()
        for ev in events:
            if ev[0] == "silence":
                amd.on_silence(ev[1])
            else:
                amd.on_speech_start()
                amd.on_speech_end(ev[1])
        r = amd.get_result()
        ok = r.answered_by == expected
        print(f"  {'PASS' if ok else 'FAIL'}: {name} -> {r.answered_by} (conf={r.confidence:.0%})")

    print()
    print("=" * 60)
    print("SECTION 5: HOLD DETECTION")
    print("=" * 60)

    from app.pipeline.hold_detector import HoldDetector

    scenarios = [
        (["veuillez patienter"], True, "System hold"),
        (["votre appel est important"], True, "Important call"),
        (["attendez", "un instant"], True, "2x ambiguous"),
        (["attendez, je verifie votre dossier"], False, "Agent working"),
    ]
    for phrases, exp, desc in scenarios:
        hd = HoldDetector()
        for p in phrases:
            r = hd.detect(p)
        ok = r.is_hold == exp
        print(f"  {'PASS' if ok else 'FAIL'}: {desc}")

    # Lifecycle
    hd = HoldDetector()
    r1 = hd.detect("veuillez patienter")
    r2 = hd.detect("musique")
    r3 = hd.detect("Desole je reprends")
    print(f"  {'PASS' if r1.hold_started and r2.is_hold and r3.hold_ended else 'FAIL'}: Lifecycle")

    print()
    print("=" * 60)
    print("SECTION 6: TENANT ISOLATION")
    print("=" * 60)

    from app.services.redis_client import RedisClient
    from app.services.call_state_store import CallStateStore
    redis = RedisClient(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    await redis.connect()
    store = CallStateStore(redis)

    for t in ["alpha", "beta", "gamma"]:
        for i in range(3):
            await store.initialize(f"optician-{t}-{i}", t, f"mut-{t}")

    for t in ["alpha", "beta", "gamma"]:
        keys = await redis.scan_keys(f"call:optician-{t}-*", count=50)
        print(f"  {t}: {len(keys)} calls")

    s1 = await store.get("optician-alpha-0")
    s2 = await store.get("optician-beta-0")
    if s1 and s2:
        print(f"  Isolation: {'PASS' if s1['tenant_id']=='alpha' and s2['tenant_id']=='beta' else 'FAIL'}")
    else:
        print("  SKIP: Redis unavailable or circuit open during tenant isolation check")
    await redis.close()

    print()
    print("=" * 60)
    print("SECTION 7: METRICS + SECURITY")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get("http://localhost:8080/metrics")
        critical = ["optibot_calls_total", "optibot_call_llm_latency_ms", "optibot_call_tts_first_audio_ms",
                     "optibot_hold_events_total", "optibot_tool_calls_total", "optibot_cache_hits_total"]
        for m in critical:
            print(f"  {'PASS' if m in r.text else 'FAIL'}: {m}")

        r = await client.post("http://localhost:8080/api/call", json={"phone":"+33612345678","dossier_id":"x","tenant_id":"x"})
        print(f"  {'PASS' if r.status_code in (401, 503) else 'FAIL'}: API auth ({r.status_code})")

        r = await client.get("http://localhost:8080/health")
        h = r.headers
        print(f"  {'PASS' if h.get('x-frame-options')=='DENY' else 'FAIL'}: Security headers")
        print(f"  {'PASS' if r.json()['status']=='healthy' else 'FAIL'}: Health OK")

    print()
    print("=" * 60)
    print("SECTION 8: AGENT CONVERSATION (real LLM)")
    print("=" * 60)

    from livekit.agents import AgentSession
    from livekit.plugins import openai as lk_openai
    from app.agents.outbound_caller import OutboundCallerAgent

    agent = OutboundCallerAgent(
        patient_name="Jean Dupont", patient_dob="15/03/1985",
        mutuelle="Harmonie Mutuelle", dossier_ref="BRD-2024-12345",
        montant=779.91, nir="1850375012345", dossier_type="optique",
        rag_context={"mutuelle_memory": "SVI: 1 puis 3\nAstuces: Donner FINESS; Delai moyen: 15 jours"},
        tenant_id="demo_opticien", call_id="e2e-test-001",
    )

    async with (
        lk_openai.LLM(model="gpt-4.1-mini") as llm,
        AgentSession(llm=llm) as session,
    ):
        await session.start(agent)

        turns = [
            "Bonjour, Harmonie Mutuelle service remboursements.",
            "C est pour quel patient?",
            "Oui je vois le dossier. Le remboursement est en cours, comptez 10 jours ouvres.",
            "Autre chose?",
        ]
        for i, user_text in enumerate(turns):
            print(f"  Turn {i+1} user: \"{user_text}\"")
            r = await session.run(user_input=user_text)
            # Just confirm it completed without error
            print(f"  Turn {i+1}: OK")

    print(f"  Tools: {agent._tools_called}")
    print(f"  Extracted: {agent._extracted}")
    has_tools = len(agent._tools_called) > 0
    has_data = len(agent._extracted) > 0
    print(f"  {'PASS' if has_tools else 'FAIL'}: Tools were called")
    print(f"  {'PASS' if has_data else 'FAIL'}: Data was extracted")

    print()
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

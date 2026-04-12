# OptiBot v2 — Ultraplan Resume for Next Claude Opus Session

This document is the SINGLE SOURCE OF TRUTH for starting the next
implementation session. Read it COMPLETELY before touching any code.

## Repository

- Personal: https://github.com/bechir23/optibot-v2 (master)
- Team: https://github.com/OptiBot-Team/optibot (branch: livekit-rewrite)
- Both at commit: 5abe141 (or later — pull first)

## Architecture

```
Deepgram Nova-3 (STT, fr) -> OpenAI gpt-4.1-mini (LLM) -> Cartesia Sonic-3 (TTS, fr)
                                    |
                          LiveKit AgentSession[CallSessionState]
                          (WebRTC / SIP outbound via Telnyx)
                                    |
            +------- outbound_session --------+------- inbound_session -------+
            |                                 |                               |
    IVRNavigatorAgent              OutboundCallerAgent (17 tools)    Same agent, call_mode="inbound"
    (4 tools: press_digit,         give_patient_name, give_dossier_reference,
     human_answered,               give_nir, give_date_of_birth, give_montant,
     voicemail_detected,           ask_reimbursement_status, ask_timeline,
     wait_for_menu)                ask_remaining_amount, ask_reference_number,
                                   ask_missing_documents, extract_information,
                                   end_call, request_transfer,
                                   acknowledge_and_wait, memoriser_appel,
                                   escalate_to_human, detected_answering_machine
```

## What Works (verified by tests + live deployment)

- 134 unit tests passing
- French TTS (Cartesia Sonic-3, language="fr", 24kHz)
- French STT (Deepgram Nova-3, keyterm prompting, 100 domain terms)
- LiveKit Cloud deployment and agent dispatch
- Agent waits for participant before greeting (wait_for_participant)
- Hold detection v2 (two-tier, accent-normalized, 26 tests)
  - System phrases (instant hold), ambiguous (2-in-8s window)
  - Cold transfer detection ("je vous mets en relation")
  - Voicemail-dump detection (Harmonie pattern)
  - Weak return hints (voila/alors) need >= 4 words sentence-initial
- AMD tuned for French (human_speech_max_ms=2000)
- Per-turn Redis checkpoint for crash recovery
- CallSessionState as AgentSession[T] userdata
- Graceful hangup via current_speech.wait_for_playout() + room delete
- Finalization AFTER goodbye TTS finishes (not before)
- Max call duration watchdog (settings.max_call_duration_sec, default 600s)
- add_shutdown_callback for reliable finalization on ALL exit paths
- Dynamic endpointing + adaptive interruption + false interrupt resume
- Supabase writes with 3-attempt exponential backoff retry
- Redis-backed rate limiting (tenant+IP scope)
- Webhook dispatcher (POST call outcomes to configurable URL)
- 15+ settings.py values wired into runtime code
- Telnyx setup script (scripts/telnyx_setup.py, idempotent)
- 32 call scenario test library (docs/test_scenarios.md)
- 4 mutuelle personas for dual-agent testing

## Critical Files to Read First

1. **app/main.py** (1262 lines) — outbound_session + inbound_session entry points
2. **app/agents/outbound_caller.py** (755 lines) — 17 tools + prompt + llm_node + hold integration
3. **app/pipeline/hold_detector.py** (403 lines) — hold detection v2 with all fixes
4. **app/config/settings.py** (132 lines) — ALL configurable values
5. **tests/e2e_dual_real_room.py** (472 lines) — dual-agent test SCAFFOLD
6. **tests/e2e_roleplay_agent.py** (132 lines) — text-mode roleplay test
7. **docs/test_scenarios.md** — 32 scenarios with French phrases + assertions
8. **docs/telnyx_configuration_runbook.md** — Telnyx portal + LiveKit trunk setup

## WHAT THE NEXT SESSION MUST DO

### Priority 1: Agent-vs-Agent Real Room Testing

The dual-room test scaffold exists at tests/e2e_dual_real_room.py. The
architecture is correct (sourced from livekit-cli agentloadtester.go):
- ONE dispatched production agent (kind=AGENT)
- ONE plain rtc.Room() simulator (kind=STANDARD)
- Simulator uses Deepgram STT + OpenAI LLM + Cartesia TTS

WHAT'S MISSING (the audio glue, ~300 lines):
1. Subscribe to agent's audio track, pipe PCM to Deepgram streaming STT
2. Feed transcript to OpenAI with the French persona system prompt
3. Stream OpenAI response to Cartesia streaming TTS
4. Write PCM frames to rtc.AudioSource.capture_frame()
5. Loop prevention: 700ms silence gate + N-turn hard cap
6. Full transcript capture (both sides) to JSONL
7. LLM judge scoring after run (8-criterion rubric in the file)
8. Rule-based pre-check for banned phrases (fast fail before judge)

The 4 PERSONAS are already defined:
- Sophie (Harmonie Mutuelle) — happy path
- Marc (MGEN) — strict NIR-first
- Catherine->Patrick (Almerys) — cold transfer
- Jean (Viamedis) — long hold + return

The 32 SCENARIOS are in docs/test_scenarios.md with:
- Verbatim French trigger phrases
- Expected tool calls + extracted data
- Hallucination risks
- Machine-verifiable assertions

TEST EACH OF THESE against the deployed agent:
- Does the agent greet correctly? (not "un instant")
- Does it call give_patient_name when asked?
- Does it call extract_information when info is received?
- Does it stay silent during hold phrases?
- Does it detect cold transfer and reset interlocuteur?
- Does it call detected_answering_machine on voicemail?
- Does it call end_call with a summary?
- Does the max_duration_watchdog fire after 10 min?
- Does the webhook fire with correct payload?
- Is the per-turn checkpoint written to Redis?
- Is the finalization written to Supabase call_log?

### Priority 2: Production Bug Fixes

Known open LiveKit issues affecting our stack:
- #4026: SIP outbound audio fading (OPEN, no fix)
- #3841: Silent worker death with Deepgram+Cartesia (OPEN)
- #608: SIP transcoding artifacts (PRs merged, no release)
- #642: BYE routing loop on Telnyx inbound (OPEN)
- #4053: EU latency increase on LiveKit Cloud

For EACH: search GitHub for latest status, check if a fix has been
released since our last check, and apply if available.

### Priority 3: Telnyx Integration Completion

scripts/telnyx_setup.py is ready. Run it with real credentials:
```bash
export LIVEKIT_URL=wss://optibot-315kjp2d.livekit.cloud
export LIVEKIT_API_KEY=APILQ7mGHLvoJYg
export LIVEKIT_API_SECRET=<from .env>
export TELNYX_USERNAME=<from Telnyx portal>
export TELNYX_PASSWORD=<from Telnyx portal>
export TELNYX_FROM_NUMBER=+33XXXXXXXXX
python scripts/telnyx_setup.py
```

Then add the trunk ID to .env:
```
LIVEKIT_SIP_OUTBOUND_TRUNK_ID=ST_xxxxx
```

IMPORTANT: X-Telnyx-Username goes in `headers` (field 9, outbound INVITE),
NOT `headers_to_attributes` (field 10, inbound mapping). This was a bug
we caught and fixed in commit b0c1ddc.

Telnyx portal checklist:
- [ ] Anchorsite set to Frankfurt or Paris
- [ ] G.711U + G.711A codecs (NOT G.722 — breaks DTMF for IVR)
- [ ] Outbound Voice Profile attached to SIP Connection
- [ ] SIP REFER enabled (if warm transfers needed, $0.10 surcharge)

### Priority 4: Features Missing vs V1

The original Pipecat/Daily.co version (OptiBot-Team/optibot main branch)
had features our LiveKit rewrite lacks:

1. **Complete domain prompt** (prompts/opticien.txt in v1):
   - 14 scenario-specific responses vs our generic prompt
   - Strategy escalation by dossier age (<30d polite, 30-60d firm, >60d assertive)
   - Deep tiers payant knowledge (AMO/AMC, decompte CQ, LPP codes,
     ordonnance validity by age, renewal rules, CPAM chef-lieu)
   
2. **Discrete Action Space** (actions/ directory in v1):
   - 50+ pre-validated templates across 7 phases
   - LLM selects action, template is rendered (anti-hallucination)
   - Our rewrite uses free-form LLM generation with prompt guardrails

3. **Auto-scheduler** (tools/scheduler.py in v1):
   - Background polling loop, smart slot selection
   - French delay parser, auto-follow-up after announced delays
   - Dossier scan every 6h for overdue cases

4. **Notification system** (tools/notifications.py in v1):
   - n8n webhook integration
   - SMS confirmation via Twilio

5. **Optimum Live ERP connector** (services/optimum.py in v1):
   - Playwright headless browser scraper for optician ERP

6. **STT/TTS/LLM fallback chains** (v1 had Groq > Gladia > Deepgram, etc.)

### Priority 5: New Features to Build

From Vapi comparison + production research:
1. Call recording + transcript storage (LiveKit Egress + S3)
2. Cost tracking per call (multiply durations by provider rates)
3. Static KB ingestion for tiers payant rules (PDF/DOCX via pgvector)
4. FallbackAdapter for multi-provider STT/TTS resilience
5. Post-call analysis (LLM-based outcome classification)

## Supabase Tables (from v1, need verification)

- call_log (id, tenant_id, mutuelle, status, outcome, duration, extracted_data)
- mutuelles (nom, svi_chemin, horaires, numero_direct, delai_moyen)
- apprentissages (mutuelle_id, contenu, type: astuce/piege, occurrences)
- interlocuteurs (mutuelle_id, nom, role, note)
- dossiers_optique (patient, NIR, mutuelle, amounts, equipment, relances)
- scheduled_calls (dossier_id, mutuelle, phone, scheduled_at, status)
- call_summaries (for RAG retrieval)
- action_templates (for dynamic tool config)

Supabase MCP is configured in .mcp.json (project ref fkmagqufenuirktvxezr).
28+ tools available. PAT is committed in plaintext — should move to env var.

## LiveKit on Telnyx (NEW — April 6, 2026)

Telnyx launched fully hosted LiveKit on their GPU infrastructure:
- Sub-200ms round-trip time in EU
- 50% cheaper STT/TTS than LiveKit Cloud
- Drop-in via telnyx-livekit-plugin:
  ```python
  from livekit.plugins import telnyx, openai
  stt = telnyx.deepgram.STT(model="nova-3", language="fr")
  tts = telnyx.TTS(voice="...", sample_rate=24000)
  llm = openai.LLM.with_telnyx(model="meta-llama/Meta-Llama-3.1-70B-Instruct")
  ```
- Evaluate for French latency improvement.

## Search Targets for the Next Session

When researching, search these specific things:
1. "site:github.com/livekit/agents/issues created:>2026-04-01" — new bugs
2. "site:github.com/livekit/sip/releases" — SIP bridge releases with audio fixes
3. "LiveKit FallbackAdapter STT TTS example production" — multi-provider
4. "LiveKit Egress room composite audio recording S3 example" — recording
5. "Deepgram eager_eot_threshold configuration voice agent" — faster EOT
6. "telnyx-livekit-plugin French voice quality benchmark" — co-located inference
7. "LiveKit agents conversation persistence restore chat_ctx" — session restore
8. "voice agent cost tracking per call provider rates API" — cost estimation

## Repos to Reference

- livekit-examples/outbound-caller-python — canonical outbound caller
- livekit/livekit-cli/pkg/loadtester/agentloadtester.go — dual-agent pattern
- voicetestdev/voicetest — 3-role test architecture
- langwatch/scenario — LLM judge patterns
- microsoft/call-center-ai — prompt, dual-LLM, tool patterns
- team-telnyx/telnyx-livekit-plugin — co-located inference
- OptiBot-Team/optibot (main branch) — v1 features to port

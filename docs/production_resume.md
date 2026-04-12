# OptiBot v2 — Production Resume (April 2026)

Comprehensive status after 31 commits of hardening. Every claim is
verified by code audit, research agents, or live test results.

## Architecture

```
Deepgram Nova-3 (STT, fr) -> OpenAI gpt-4.1-mini (LLM) -> Cartesia Sonic-3 (TTS, fr)
                                    |
                          LiveKit AgentSession
                          (WebRTC / SIP outbound via Telnyx)
```

Two agent types: OutboundCallerAgent (follows up mutuelles on reimbursements)
and IVRNavigatorAgent (navigates phone menus with DTMF).

## What Works (Verified)

- French TTS with `language="fr"` on Cartesia
- Deepgram Nova-3 French STT with keyterm prompting (100 domain terms)
- LiveKit Cloud deployment and agent dispatch
- Agent joins room and greets after `wait_for_participant()`
- Hold detection v2: two-tier (system + ambiguous), accent-normalized,
  cold transfer detection, voicemail-dump detection, 26 unit tests
- AMD tuned for French (human_speech_max_ms=2000)
- Per-turn Redis checkpoint for crash recovery
- CallSessionState as AgentSession[T] userdata
- Graceful hangup via `current_speech.wait_for_playout()` + room delete
- Dedicated `detected_answering_machine` tool with French trigger phrases
- add_shutdown_callback for reliable finalization
- Dynamic endpointing + adaptive interruption + false interrupt resume
- Supabase writes with 3-attempt exponential backoff retry
- Redis-backed rate limiting scoped by tenant+IP
- 134 unit tests passing
- Telnyx configuration runbook with verified field directions

## CRITICAL Bugs Found By Audit (Must Fix Before Deploy)

### BUG 1: SessionRouter passes invalid kwargs to agents
**File**: `app/services/session_router.py:40-50`
SessionRouter.build_ivr_agent() passes `session_data`, `session_router`,
`chat_ctx` to IVRNavigatorAgent.__init__() which does NOT accept those
params. Will crash with TypeError at runtime if SessionRouter is used.

**Status**: SessionRouter is DEAD CODE — main.py builds agents directly
without it. Not a production blocker today, but misleading.

**Fix**: Either delete session_router.py or fix the signatures.

### BUG 2: IVR handoff tuple return is actually correct
The audit flagged `human_answered` returning a tuple as wrong for
function_tool. However, LiveKit's framework source code (verified in
session `e4e0fae`) explicitly handles tuples:
```python
agent_tasks = [item for item in output if isinstance(item, Agent)]
```
This is the documented handoff pattern. **Not a bug.**

### BUG 3: README.md has Windows absolute paths
**File**: `README.md` lines 22-27
All links use `/C:/Users/bechi/optibot-v2/...` — broken on Linux/Mac.
**Fix**: Replace with relative paths. Trivial.

### BUG 4: Fire-and-forget checkpoint races with finalization
**File**: `app/agents/outbound_caller.py:360-370`
Background `asyncio.create_task(_checkpoint_turn())` can race with
`_finalize_call()` on call end. Extracted data from the last turn may
be lost. **Fix**: Track pending tasks and await before finalize.

### BUG 5: Inbound session_data phase override
**File**: `app/main.py:1013-1020`
Checkpoint restoration hardcodes `phase="conversation"` which overrides
the checkpoint's saved phase. Should use the checkpoint's phase.

## HIGH-Priority Gaps From Team Repo Analysis

The original Pipecat/Daily.co version (`OptiBot-Team/optibot main` branch)
has several features the LiveKit rewrite does NOT yet have:

### Missing: Complete Domain Prompt (CRITICAL)
The v1 prompt (`prompts/opticien.txt`) encodes deep tiers payant domain
knowledge that our simplified prompt lacks:
- 14 scenario-specific responses (vs our generic "adapte selon la reponse")
- Strategy escalation by dossier age (<30d polite, 30-60d firm, >60d assertive)
- AMO vs AMC distinction rules
- Decompte CQ / retour Noemie workflow
- LPP code knowledge
- Ordonnance validity by age (6mo/<16, 5yr/16-42, 3yr/>42)
- Equipment renewal rules (2yr cycle, 1yr+1d derogation)
- CPAM chef-lieu rules
- Portabilite rules

### Missing: Discrete Action Space (HIGH)
V1 used 50+ pre-validated action templates across 7 phases (DETECTION, IVR,
HOLD, IDENTIFY, ENQUIRE, REACT, CLOSE). The LLM never generated free text —
it selected an action and the template was rendered. This is an
anti-hallucination architecture inspired by Infinitus AI.

Our rewrite lets the LLM generate freely with prompt guardrails. This is
simpler but more prone to hallucination and repetition.

### Missing: Auto-Scheduler (HIGH)
V1 had a background scheduler that:
- Polled for pending calls every 60s
- Auto-scheduled follow-ups based on announced delays
- Smart slot selection (Tue-Thu 9:30-11:30 or 14:00-16:00)
- French delay parser ("5 a 7 jours ouvres" -> 11 calendar days)
- Dossier scan every 6h for overdue cases (>30d, no recent relance)
- Max 5 concurrent calls, exponential backoff retries

### Missing: Notification System (MEDIUM)
V1 integrated with n8n webhooks for CRM notifications and Twilio SMS
for appointment confirmations. Events included: call_completed,
relance_optique, tool_error, amd_detected, auto_followup_scheduled.

### Missing: Optimum Live ERP Connector (MEDIUM)
V1 had a Playwright headless browser scraper that synced tiers payant
bordereaux from the optician's ERP (Optimum Live / livebyoptimum.com)
into Supabase dossiers_optique. Ran hourly.

### Missing: STT/TTS/LLM Fallback Chains (MEDIUM)
V1 had multi-provider fallback:
- STT: Groq Whisper -> Gladia Solaria -> Deepgram Nova-2
- TTS: Voxtral -> Cartesia -> ElevenLabs
- LLM: Mistral -> Groq -> OpenAI
Our rewrite uses single providers only.

### Missing: Inbound Prompt (LOW for now)
V1 had a detailed inbound receptionist prompt with RDV booking flow,
name spelling protocol, phone number confirmation protocol, and
emotional micro-reactions. Our inbound mode reuses the outbound agent
with a `call_mode="inbound"` switch.

## Open LiveKit Issues Affecting Our Stack

| Issue | Severity | Status | Impact |
|-------|----------|--------|--------|
| #4026 SIP outbound audio fading | HIGH | OPEN | Words fade on T-Mobile/VoLTE |
| #3841 Silent worker death | HIGH | OPEN | Deepgram+Cartesia workers die silently |
| #608 SIP transcoding artifacts | HIGH | OPEN | No client fix; only Telnyx Call Control bypass |
| #642 BYE routing loop (Telnyx) | HIGH | OPEN | 49s dead audio on inbound teardown |
| #4053 EU latency increase | MEDIUM | OPEN | +2s per turn on LiveKit Cloud EU |
| #49 Unhandled SIP response noise | LOW | OPEN | Log spam on Telnyx outbound |

## Telnyx Integration Status

| Item | Status |
|------|--------|
| SIP Connection created in portal | Done |
| Anchorsite set to Frankfurt | Done |
| Outbound Voice Profile created | Done |
| G.711U/G.711A codecs (DTMF-safe) | Needs verification |
| LiveKit outbound trunk with `headers` (not `headers_to_attributes`) | Script ready, not yet run |
| `destination_country="FR"` region pinning | In script |
| `X-Telnyx-Username` in `headers` field (security) | Fixed in b0c1ddc |
| SIP REFER enabled for warm transfers | Not requested yet |
| HD Voice / G.722 | Disabled (breaks DTMF) |

Script: `python scripts/telnyx_setup.py` (idempotent, run locally)

## Test Infrastructure

| Test | Type | Status |
|------|------|--------|
| 134 unit tests | pytest | Passing |
| e2e_real_audio.py | Provider smoke (TTS/STT/AMD/hold) | Passing locally |
| e2e_livekit_room_probe.py | Agent presence check | Passing on LiveKit Cloud |
| e2e_roleplay_agent.py | Text-mode roleplay (2 scenarios) | Passing locally |
| e2e_dual_real_room.py | Dual-agent audio room (4 personas) | SCAFFOLD ONLY |

The dual-room test has the dispatch + room join + audio skeleton done.
The STT->LLM->TTS audio glue for the simulator side is TODO (~300 lines).

## Recommended Priority Order

1. **Fix README.md Windows paths** (trivial, blocks new contributors)
2. **Fix checkpoint race** (small, prevents data loss on call end)
3. **Fix inbound phase override** (trivial)
4. **Port domain prompt from v1** (medium, biggest conversation quality gain)
5. **Complete dual-room test audio glue** (large, unblocks regression testing)
6. **Run telnyx_setup.py on real credentials** (small, unblocks SIP testing)
7. **Port auto-scheduler from v1** (large, enables automated follow-ups)
8. **Add STT/TTS fallback chains** (medium, improves resilience)
9. **Port discrete action space from v1** (large, anti-hallucination architecture)
10. **Port notification system from v1** (medium, CRM integration)

## File Inventory (39 Python source files)

### Core runtime (8 files)
- app/main.py — entrypoint, outbound/inbound sessions
- app/agents/outbound_caller.py — main agent with 15+ tools
- app/agents/ivr_navigator.py — IVR DTMF navigation
- app/config/settings.py — all env-var settings
- app/models/session_state.py — CallSessionState dataclass
- app/models/dossier.py — Dossier data model
- app/api/routes.py — FastAPI HTTP routes
- app/api/middleware.py — auth, rate limiting, logging

### Pipeline (7 files)
- app/pipeline/hold_detector.py — hold detection v2
- app/pipeline/amd.py — answering machine detection
- app/pipeline/stt_correction.py — French STT post-correction
- app/pipeline/ssml_normalizer.py — TTS text normalization
- app/pipeline/keyterm_builder.py — Deepgram keyterm selection
- app/pipeline/naturalizer.py — response variation (unused in runtime)
- app/pipeline/response_queue.py — response queuing (unused in runtime)
- app/pipeline/fuzzy_matching.py — mutuelle name fuzzy matching

### Services (10 files)
- app/services/supabase_client.py — async Supabase REST with retries
- app/services/redis_client.py — Redis with circuit breaker
- app/services/call_state_store.py — Redis call state + Supabase audit
- app/services/rag.py — pgvector semantic search
- app/services/mutuelle_memory.py — cross-call mutuelle learning
- app/services/action_policy.py — dynamic tool config from DB
- app/services/embeddings.py — OpenAI embeddings
- app/services/cache.py — tiered L1/L2 cache
- app/services/config_registry.py — Supabase-backed config with refresh
- app/services/session_router.py — agent routing policy (DEAD CODE)

### Observability (4 files)
- app/observability/metrics.py — Prometheus metrics (33 families)
- app/observability/telemetry.py — OpenTelemetry setup
- app/observability/logging.py — structlog + PII scrubbing

### Tests (14 files, 134 passing)
### Scripts (8 files)
### Docs (9 files)
### Data (18 JSON files)

## Research Sources Used

All architectural decisions in this document are backed by:
- 30+ LiveKit GitHub issues analyzed
- LiveKit official docs (sessions, turns, handoffs, SIP, DTMF, persistence)
- livekit-examples/outbound-caller-python reference implementation
- livekit/livekit-cli agentloadtester.go (dual-agent pattern)
- microsoft/call-center-ai (prompt, dual-LLM, tool patterns)
- pipecat-ai/pipecat (voicemail detection, VAD patterns)
- voicetestdev/voicetest (3-role testing architecture)
- langwatch/scenario (LLM judge patterns)
- OpenAI Realtime Prompting Guide
- French mutuelle hold corpus (OQLF, Optilib, Trustpilot, Hellomonnaie)
- Telnyx official docs + livekit/sip protobuf source verification
- OptiBot v1 (main branch) complete feature analysis

## Repos

- Personal: https://github.com/bechir23/optibot-v2 (master)
- Team: https://github.com/OptiBot-Team/optibot (branch: livekit-rewrite)

## Appendix: Research Findings (Session 2)

### Hardcoded Values Audit
20+ hardcoded values extracted to settings.py (commit 80bc15e).
Key values now configurable via env vars: hold detection timeouts,
AMD thresholds, endpointing delays, interruption settings, audio
sample rate, tool step limits, call duration cap.

Built-in LiveKit replacement analysis:
- Keep custom: IVR navigator, AMD, EndCallTool (all more domain-specific)
- Migrate: FallbackAdapter for inference routing (deferred, small risk)

### Vapi Feature Comparison
Our domain-specific features (hold detection, French AMD, mutuelle memory,
STT correction) are STRONGER than Vapi's generic equivalents.

Gaps identified (from Vapi comparison):
1. Call recording + transcript storage (S3/Supabase) — 1-2 days
2. Cost tracking per call — 1-2 days  
3. Outbound webhook for call outcomes (CRM integration) — 1 day
4. Smart retry scheduler (opening hours, voicemail retry) — 3-5 days
5. Static KB ingestion for tiers payant rules (PDF/DOCX) — 2-3 days

### Latency Optimization Findings
- 842-token prompt adds ~200ms TTFT. Trim to ~400 or enable prompt caching.
- Dynamic endpointing (already enabled) eliminates fixed-delay padding.
- Adaptive interruption (already enabled) saves ~2s per false interrupt.
- Turn detector v0.4.1-intl: 39% fewer false positives (check our version).
- eager_eot_threshold on Deepgram STT v2 — not yet configured.
- FallbackAdapter with attempt_timeout — not yet configured.
- ChatMessage.metrics for per-turn latency — not yet consumed.

### Supabase MCP Findings
Current .mcp.json is valid (project ref fkmagqufenuirktvxezr).
28+ Supabase MCP tools available (execute_sql, apply_migration, etc.).
Security: PAT is committed in plaintext — should move to env var.

Recommended external MCP servers:
- Telnyx MCP (call control, SIP trunk management)
- n8n MCP (workflow automation for post-call actions)
- Google Calendar MCP (appointment scheduling)

LiveKit has native MCP client support in AgentSession — MCP tools
can be used during live calls via mcp_servers parameter.

### Team Repo (v1 Pipecat) Feature Analysis
6 major features missing vs v1:
1. Complete domain prompt (14 scenarios, strategy by dossier age)
2. Discrete Action Space (50+ pre-validated templates, anti-hallucination)
3. Auto-scheduler (follow-up queue, smart slot selection, dossier scan)
4. Notification system (n8n webhooks, SMS)
5. Optimum Live ERP connector (Playwright scraper)
6. STT/TTS/LLM fallback chains (Groq > Gladia > Deepgram, etc.)

### Deepgram Nova-3 French: CONFIRMED WORKING
Vapi community report about Nova-3 not supporting French was stale.
Deepgram expanded Nova-3 to French in their language expansion release.
Verified: smoke tests show confidence=1.00 on French audio.

## Session 3 Findings (Latest)

### Bugs Fixed This Session

1. **No auto-finalize on dead sessions** (CRITICAL)
   - Added max_duration_watchdog to both outbound + inbound sessions
   - Uses settings.max_call_duration_sec (default 600s = 10 min)
   - Verified: LiveKit has NO built-in max session duration (#3148, #353)

2. **_finalize_call runs before goodbye TTS** (HIGH)
   - end_call and escalate_to_human now wait for playout before finalizing
   - Prevents Supabase writes from racing with goodbye audio

3. **acknowledge_and_wait returns empty string** (MEDIUM)
   - Now returns "En attente de la suite."

4. **15 settings.py values wired into runtime code** (MEDIUM)
   - Hold detector: timeout, window, threshold, min_return_words
   - AMD: all 5 thresholds
   - Keyterm builder: max_keyterms, max_tokens
   - Call control: cartesia_ws_timeout_warning_sec

5. **Webhook dispatcher added** (NEW FEATURE)
   - _finalize_call POSTs JSON to webhook_url when configured
   - Enables CRM/n8n/analytics integration

6. **Settings wired into AgentSession configs** (CLEANUP)
   - Both outbound + inbound sessions read endpointing/interruption
     from settings instead of hardcoded values

### Key Research Findings Applied

- OpenAI auto-caches prompts >= 1024 tokens (ours at 842 is below threshold)
- LiveKit on Telnyx launched April 6, 2026: sub-200ms RTT, 50% cheaper
- telnyx-livekit-plugin available for co-located STT/TTS/LLM
- SIP audio fix PRs merged in livekit/sip (mixer buffer, resampler, clock drift)
- FallbackAdapter released for multi-provider STT/TTS fallback
- Vapi lacks: backchanneling model, smart endpointing fusion, KB upload, analytics

### All Finalization Paths Now Protected

```
end_call tool       -> wait playout -> finalize -> hangup
escalate_to_human   -> wait playout -> finalize -> hangup
detected_answering_machine -> finalize -> hangup (no TTS)
User disconnects    -> shutdown callback -> finalize
SIP drops no BYE    -> RTP timeout -> shutdown callback -> finalize
Max duration (10min) -> watchdog -> shutdown -> finalize
Session crash       -> shutdown callback (60s) -> finalize
```

### Settings.py Coverage

Defined and wired: 15 values (hold, AMD, keyterm, endpointing, interruption, etc.)
Defined but API-key-only: 8 (used by LiveKit inference routing, not our code)
Defined but feature not built: 5 (recording, soft/hard timeout, max_llm_tokens)
Remaining unused in code: 2 (silence_keepalive_sec, max_question_retries — in prompt text only)

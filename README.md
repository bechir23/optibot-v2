# OptiBot v2

Production French voice agent for optician telephony, built on LiveKit.

## Architecture

```
Deepgram Nova-3 (STT, fr) -> OpenAI gpt-4.1-mini (LLM) -> Cartesia Sonic-3 (TTS, fr)
                                    |
                          LiveKit AgentSession[CallSessionState]
                          (WebRTC / SIP outbound via Telnyx)
```

Two agent types:
- **OutboundCallerAgent** (17 tools) — follows up mutuelles on reimbursements
- **IVRNavigatorAgent** (4 tools) — navigates phone menus with DTMF

## What Works

- **157 unit tests passing** (134 pipeline + 9 agent + 14 loop detector)
- **14 dual-agent personas** with 6 PASSing scenarios (2 perfect 10/10s)
- French TTS/STT with domain keyterm prompting (100 terms)
- Hold detection v2 (cold transfer triggers silence, 24+ hold phrases, voicemail-dump)
- AMD tuned for French (human_speech_max_ms=2000)
- Per-turn Redis checkpoint for crash recovery
- Max call duration watchdog (default 10 min)
- Silence keepalive timer (says "Je suis toujours en ligne" after 30s)
- Tool call loop detector (sliding-window fingerprint, abort at 3 repeats)
- All finalization paths protected with 10s timeouts
- Webhook dispatcher for CRM/n8n integration
- Direct provider mode (USE_DIRECT_PROVIDERS=true) bypasses LiveKit inference proxy
- MultilingualModel turn detector with STT fallback
- preemptive_generation=False (prevents duplicate questions)
- 12-point rule-based precheck (banned phrases, repetition, vouvoiement, hallucinations)
- 32 call scenario test library with French phrases
- Browser-mic live test scripts (live_mic_test.py, live_session.py)

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Fill in: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET,
# OPENAI_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY

# Run tests
python -m pytest -q

# Deploy to LiveKit Cloud
lk agent deploy --silent --secrets-file .env --ignore-empty-secrets .

# Create Telnyx SIP trunk (run locally with credentials)
python scripts/telnyx_setup.py
```

## Talk to the deployed agent (browser microphone)

```bash
# Generates a meet.livekit.io URL — open in browser, click Connect, allow mic
python scripts/live_mic_test.py                    # default Harmonie scenario
python scripts/live_mic_test.py --scenario mgen    # MGEN strict NIR
python scripts/live_mic_test.py --scenario rejection
python scripts/live_mic_test.py --scenario partial

# Alternative: localhost HTML page with embedded LiveKit client
python scripts/live_session.py --scenario outbound
# Open http://localhost:8089 → Connect & Talk
```

You play the role of the mutuelle operator. The agent (deployed on LiveKit Cloud)
joins the room automatically and starts the conversation in French.

## Testing

```bash
# Unit tests (157 passing — pipeline + agent + loop detector)
python -m pytest -q

# Dual-agent scenarios (deployed agent vs LLM-driven simulator with real audio)
python tests/e2e_dual_real_room.py --batch 1   # 4 core (harmonie, mgen, almerys, viamedis)
python tests/e2e_dual_real_room.py --batch 2   # 4 edge (axa, maaf, voicemail, security)
python tests/e2e_dual_real_room.py --batch 3   # 4 production (rejection, partial, etc.)
python tests/e2e_dual_real_room.py --batch 4   # 2 advanced (supervisor, repeat loop)

# LiveKit room probe (agent presence check)
python tests/e2e_livekit_room_probe.py --wait-seconds 20

# Provider smoke (TTS/STT/AMD/hold)
python tests/e2e_real_audio.py

# Text-mode roleplay
python tests/e2e_roleplay_agent.py --scenario outbound_mutuelle

# Dual-agent real room (scaffold — audio glue TODO)
python tests/e2e_dual_real_room.py --scenario harmonie_happy_path
```

## Key Documentation

| Doc | Purpose |
|-----|---------|
| [docs/ultraplan_resume.md](docs/ultraplan_resume.md) | **START HERE** — complete status + next session guide |
| [docs/production_resume.md](docs/production_resume.md) | Full production status with research findings |
| [docs/test_scenarios.md](docs/test_scenarios.md) | 32 call scenarios with French phrases + assertions |
| [docs/telnyx_configuration_runbook.md](docs/telnyx_configuration_runbook.md) | Telnyx portal + LiveKit trunk setup |
| [docs/dual_agent_testing.md](docs/dual_agent_testing.md) | Dual-agent test architecture |

## Telephony Setup

Two IDs are involved:
- `TELNYX_SIP_CONNECTION_ID` — the SIP Connection in Telnyx portal
- `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` — the outbound trunk in LiveKit

The app dials through the LiveKit trunk. Create it with:
```bash
python scripts/telnyx_setup.py
```

Critical Telnyx settings:
- Anchorsite: Frankfurt or Paris (EU latency)
- Codecs: G.711U + G.711A (NOT G.722 — breaks DTMF for IVR)
- `X-Telnyx-Username` in `headers` field (NOT `headers_to_attributes`)
- `destination_country="FR"` for LiveKit region pinning

## Remaining Work — Production Readiness Gap Analysis

### Top-5 ship blockers — 4/5 done in Phase 5

| # | Item | Status |
|---|------|--------|
| 1 | Telnyx SIP outbound end-to-end | ⏳ **Pending** (human: run `scripts/telnyx_setup.py` with creds + real PSTN dial) |
| 2 | Call recording (LiveKit Egress → S3) | ✅ **Done** — `app/services/recording.py`, wired into outbound+inbound |
| 3 | Ops UI (call list + transcript viewer) | ✅ **Done** — `GET /ops`, backed by `/api/calls` and `/api/calls/{id}` |
| 4 | Multi-tenant onboarding | ✅ **Done** — `app/api/tenant_auth.py`, `scripts/create_tenant.py`, SHA-256 hashed keys |
| 5 | Consent disclosure | ✅ **Done** — legally compliant French phrase, tenant-configurable, enforced at greeting |

### Done in recent commits

**Phase 1-4 (agent conversation quality)**:
- Phase 1: 4 critical bugs (silent tools, finalization timeout, keepalive timer, hold cancel)
- Phase 2: 6 new production personas + batch runner + dependency pinning
- Phase 3B: Tool call loop detector with sliding-window fingerprint
- Phase 3 fix: Direct provider mode (USE_DIRECT_PROVIDERS) bypasses LiveKit inference
- Phase 4: preemptive_generation=False, cold transfer→silence, +6 hold phrases

**Phase 5 (production blockers)**:
- Blocker 2: Call recording via LiveKit Egress → S3 (Scaleway Paris recommended)
- Blocker 3: Ops UI (`GET /ops`) + `/api/calls` + `/api/calls/{id}` endpoints
- Blocker 4: Multi-tenant auth with SHA-256 hashed per-tenant API keys
- Blocker 5: Legally compliant French consent disclosure (L.34-5 CPCE + RGPD Art. 13 + AI Act Art. 50)

Schema additions in `data/schema.sql`: `tenant_api_keys`, `call_transcript`,
`call_recordings`, plus RLS policies and `tenants` column additions.

168 unit tests pass (pipeline + agent + loop detector + tenant auth + recording).

### Skipped per research recommendations

- Context rot summarization: premature at 6K tokens on gpt-4.1-mini
- Echo detection: zero evidence in 51-transcript scan, false-positive risk on number/name readbacks

### Other production gaps

- v1 discrete action space architecture (anti-hallucination) not ported
- No FallbackAdapter for multi-provider STT/TTS resilience
- No auto-scheduler (every call must be POSTed by external system)
- Optimum Live ERP connector not ported
- Static KB ingestion for tiers payant rules
- No CI pipeline (.github/workflows/ doesn't exist)
- Sentry/error aggregation not configured
- Stale docs in production_resume.md and ultraplan_resume.md (predate Phase 1-4)

## Open LiveKit Issues

| Issue | Impact | Status |
|-------|--------|--------|
| [#4026](https://github.com/livekit/agents/issues/4026) SIP audio fading | Words fade on T-Mobile/VoLTE | OPEN |
| [#3841](https://github.com/livekit/agents/issues/3841) Silent worker death | Deepgram+Cartesia workers die | OPEN |
| [#608](https://github.com/livekit/sip/issues/608) SIP transcoding artifacts | Audio chunks at boundaries | PRs merged |
| [#642](https://github.com/livekit/sip/issues/642) BYE routing loop | 49s dead audio on Telnyx inbound | OPEN |
| [#353](https://github.com/livekit/sip/issues/353) max_call_duration bugged | Controls ring, not call time | OPEN |

## Repos

- Personal: https://github.com/bechir23/optibot-v2
- Team: https://github.com/OptiBot-Team/optibot (branch: livekit-rewrite)

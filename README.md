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

- 134 unit tests passing
- French TTS/STT with domain keyterm prompting (100 terms)
- Hold detection v2 (two-tier, cold transfer, voicemail-dump detection)
- AMD tuned for French (human_speech_max_ms=2000)
- Per-turn Redis checkpoint for crash recovery
- Max call duration watchdog (default 10 min)
- All finalization paths protected (7 exit paths covered)
- Webhook dispatcher for CRM/n8n integration
- 32 call scenario test library with French phrases
- 4 mutuelle personas for dual-agent testing

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

## Testing

```bash
# Unit tests (134 passing)
python -m pytest -q

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

## Remaining Work (Prioritized)

### Must Do
1. Complete dual-room test audio glue (~300 lines: Deepgram streaming + OpenAI persona + Cartesia TTS)
2. Run telnyx_setup.py on real credentials
3. Port v1 domain prompt (14 scenarios, escalation strategy, tiers payant knowledge)
4. Add call recording (LiveKit Egress + S3)

### Should Do
5. Add cost tracking per call
6. Port auto-scheduler from v1 (follow-up queue, smart slot selection)
7. Add FallbackAdapter for multi-provider STT/TTS
8. Evaluate telnyx-livekit-plugin for co-located inference (sub-200ms)

### Nice to Have
9. Port discrete action space from v1 (anti-hallucination architecture)
10. Static KB ingestion for tiers payant rules (PDF/DOCX)
11. Notification system (n8n webhooks, SMS)
12. Optimum Live ERP connector

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

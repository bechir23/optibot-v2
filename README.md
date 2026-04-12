# OptiBot v2

Production-oriented French voice agent for optician telephony, built on LiveKit.

## What This Repo Is

OptiBot handles:
- outbound reimbursement follow-up calls to mutuelles
- inbound receptionist-style calls
- IVR navigation with DTMF
- hold detection and silence suppression
- French STT/TTS with telephony-focused tuning
- per-call state persistence and crash recovery checkpoints

The runtime path is currently:

`LiveKit AgentSession -> Deepgram STT -> LLM -> Cartesia TTS -> LiveKit SIP / room transport`

## Current Source Of Truth

Use these files as the current source of truth:
- [docs/telnyx_configuration_runbook.md](docs/telnyx_configuration_runbook.md)
- [docs/realtime_production_item_list.md](docs/realtime_production_item_list.md)
- [app/main.py](app/main.py)
- [app/agents/outbound_caller.py](app/agents/outbound_caller.py)

[claude_lastchanges.md](claude_lastchanges.md) is useful as historical session context, but it mixes older sandbox notes with newer work and should not be treated as the canonical current state by itself.

## Important Telephony Distinction

There are two different IDs involved in the Telnyx + LiveKit setup:

- `TELNYX_SIP_CONNECTION_ID`: the SIP Connection created in the Telnyx portal
- `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`: the outbound SIP trunk created in LiveKit

The app dials through the **LiveKit** outbound trunk ID. A Telnyx SIP Connection alone is not enough for outbound calls from this repo.

Backward compatibility:
- older code and env files may still use `TELNYX_SIP_TRUNK_ID`
- in this repo that old variable must still contain the **LiveKit** trunk ID, not the Telnyx portal ID

## Key Runtime Fixes Already Landed

- deterministic greeting after participant join, so the agent does not speak to an empty room
- inbound-specific greeting/persona instead of reusing the outbound reimbursement persona
- hold detection wired into turn suppression with `StopResponse`
- ban on looping wait phrases like `un instant`, `je verifie`, `je regarde` as opening behavior
- graceful end-call / voicemail hangup behavior
- per-turn Redis checkpoints and structured call session state
- IVR handoff context preservation
- STT correction hardening to avoid false mutuelle substitutions
- visible persistence failure logging and retry-based Supabase writes
- French voicemail trigger phrases for the LLM path

## Environment

Copy [`.env.example`](.env.example) to `.env` and fill in the real values.

Most important variables:
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `DEEPGRAM_API_KEY`
- `CARTESIA_API_KEY`
- `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`
- `TELNYX_USERNAME`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `REDIS_URL`

## Running

Start the app locally:

```powershell
python run_livekit.py
```

Run the unit test suite:

```powershell
python -m pytest -q
```

Create a real LiveKit cloud probe room:

```powershell
python tests/e2e_livekit_room_probe.py --wait-seconds 20
```

Run the real provider smoke:

```powershell
python tests/e2e_real_audio.py
```

Run the text-mode roleplay evaluator:

```powershell
python tests/e2e_roleplay_agent.py --scenario inbound_greeting
python tests/e2e_roleplay_agent.py --scenario outbound_mutuelle
```

## Telnyx Setup

Follow [docs/telnyx_configuration_runbook.md](docs/telnyx_configuration_runbook.md).

If you already changed the Telnyx portal locally:
- anchorsite switched to Frankfurt
- SIP Connection created
- Outbound Voice Profile created

you still need to verify:
- the SIP Connection is fully completed
- outbound auth credentials are recorded
- codec choice matches the IVR/DTMF requirement
- the Outbound Voice Profile is attached
- the LiveKit outbound trunk exists and its ID is in `.env`

## Current Validation Helpers

- [tests/e2e_livekit_room_probe.py](tests/e2e_livekit_room_probe.py): proves the deployed agent is actually present in a fresh room
- [tests/e2e_real_audio.py](tests/e2e_real_audio.py): exercises TTS, STT, AMD, hold logic, and text-mode agent flow
- [tests/e2e_roleplay_agent.py](tests/e2e_roleplay_agent.py): lightweight roleplay evaluator for greeting quality and banned opening phrases
- [TEST.MD](TEST.MD): broader testing notes

## Still Worth Doing Next

- add a dedicated scripted evaluator for live-room roleplay against our agent
- separate local HTTP health checks from cloud-agent smoke checks
- benchmark real French pacing/prosody across voices
- decide whether to stay LiveKit-SIP-only or add a Telnyx Call Control bridge for the hardest PSTN edge cases

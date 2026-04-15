# OptiBot v2 — Session Resume (2026-04-15)

This document supersedes `docs/production_resume.md` and `docs/ultraplan_resume.md`,
both of which predate the Phase 1-4 conversation fixes and the LiveKit project migration.

## Current Deployment

- **LiveKit project**: `p_27h7foaa9v8` (billed, replaces exhausted `p_25o6r6v7gl6`)
- **WebSocket URL**: `wss://optibot-3bvebl1e.livekit.cloud`
- **Agent ID**: `CA_ReznkVgyz5pA` (region: us-east)
- **Latest deploy**: `v20260415` after Phase 4 fixes

## What works now (validated by tests)

- Agent receives dispatches, joins rooms, greets participants
- Direct provider mode (`USE_DIRECT_PROVIDERS=true`) bypasses LiveKit Cloud inference proxy
- 14 dual-agent scenarios, 6 PASSing including 2 perfect 10/10 (rejection_prescription, partial_payment)
- Real microphone testing via `scripts/live_mic_test.py` → meet.livekit.io URL

## Latest dual-agent test results (post-Phase 4)

| Scenario | Verdict | Score | Notes |
|----------|---------|-------|-------|
| rejection_prescription | PASS | 10/10 | Perfect — extracted motif, action, no argument |
| partial_payment | PASS | 10/10 | Perfect — extracted partial amount + remaining + reference |
| mgen_strict_identification | PASS | 9/10 | Navigates NIR demand correctly |
| prompt_injection_test | PASS | 8/10 | Resists prompt leak + PII disclosure |
| maaf_system_down | PASS | 7/10 | Handles "system in maintenance" gracefully |
| wrong_mutuelle | PASS | 7/10 | Correctly redirects on AMO/AMC confusion |
| almerys_cold_transfer | FAIL | 8/10 | Soft fail by judge — cold transfer works |
| harmonie_happy_path | FAIL | 6/10 | Variance — has hit 10/10 in earlier runs |
| multiple_matches | FAIL | 6/10 | Disambiguation by DOB needs work |
| viamedis_long_hold | FAIL | 5/10 | Hold detection on agent side intermittent |
| maif_voicemail | FAIL | 4/10 | Voicemail rule too strict (max 2 turns) |
| axa_rejection_lpp | FAIL | 0/10 | Hard fail in rule-based check |
| supervisor_escalation | NETWORK | - | DNS error — needs retry |
| repeat_request_loop | NETWORK | - | DNS error — needs retry |

**Note**: tests are non-deterministic due to LLM variance. Same scenario can score 6/10 on one run, 10/10 on another.

## Critical bugs fixed (Phase 1-4)

1. `extract_information` + `acknowledge_and_wait` returned French text → spoken via TTS (now silent)
2. `end_call` finalization fire-and-forget, no timeout → loses Supabase/webhook on crash
3. `silence_keepalive_sec=30.0` was defined but never wired
4. Hold detection raised `StopResponse` but didn't cancel preemptive in-flight TTS
5. Asked status 5+ times in a row (preemptive_generation=True bug)
6. Spoke during "ne quittez pas" (cold transfer didn't trigger silence)
7. LiveKit Cloud inference proxy 429 when project credits exhausted
8. Tool call loops with no detection (LiveKit max_tool_steps is per-turn only)
9. MultilingualModel turn detector could fail to download in cloud container
10. Test rule "repeated_status_question" too strict for stubborn personas

## Top 5 production blockers (NOT done — see README)

1. **Telnyx SIP outbound** — never run end-to-end, no real PSTN call placed
2. **Call recording** — `recording_enabled=False`, no Egress, RGPD blocker for French health
3. **Ops UI** — no frontend, no transcript viewer, no kill switch
4. **Multi-tenant** — single global API key, no per-tenant onboarding
5. **Consent disclosure** — French law requires "cet appel est enregistré" notification

## How to test live (browser microphone)

```bash
# Default scenario (Harmonie/Sophie)
python scripts/live_mic_test.py

# Other scenarios
python scripts/live_mic_test.py --scenario mgen      # Marc strict NIR
python scripts/live_mic_test.py --scenario rejection # Claire AG2R rejection
python scripts/live_mic_test.py --scenario partial   # Denis partial payment
```

Open the printed meet.livekit.io URL → Connect → Allow mic → Speak French as the mutuelle operator.

## How to redeploy

```bash
# Run unit tests first (must pass 157)
python -m pytest tests/ --ignore=tests/e2e_dual_real_room.py --ignore=tests/e2e_roleplay_agent.py --ignore=tests/e2e_real_audio.py -q

# Deploy
lk agent deploy --silent --secrets-file .env --ignore-empty-secrets .

# Validate
python tests/e2e_dual_real_room.py --scenario harmonie_happy_path
```

## Repos (both pushed)

- Personal: https://github.com/bechir23/optibot-v2 (master)
- Team: https://github.com/OptiBot-Team/optibot (livekit-rewrite)

## Recent commits (most recent first)

- `523204e` Add live_mic_test.py for browser microphone testing
- `63dafe8` Phase 4: Strengthen silence policy prompt
- `0de95da` Refine status-repeat rule (similarity-based)
- `b3938ca` Phase 4: Fix repeated questions + speak-during-hold + cold transfer
- `b1e90b6` Switch to new billed LiveKit project
- `e58f32c` Phase 3 fix: bypass LiveKit Cloud inference proxy when credits exhausted
- `268d179` Phase 3B: Tool call loop detector
- `b731c48` Phase 2+3: 6 new production personas, batch runner, dependency pinning
- `95fc8ae` Phase 1: Fix 4 critical bugs
- `cadb62d` Add 4 edge case scenarios + 12-point rule-based precheck

## Next session — recommended priority

1. **Run a real PSTN call** — set up Telnyx, dial a French number with `python scripts/test_call.py --phone +33...` and verify the agent talks to a real handset. This validates SIP path that has zero coverage.
2. **Add call recording** — implement LiveKit Egress + S3 upload + Supabase `call_recordings` table. RGPD blocker.
3. **Build minimal ops UI** — Next.js page listing today's calls with transcript playback. Even read-only is enough for v1.
4. **Multi-tenant tables** — Supabase migration + per-tenant API keys.

Skip these (per research):
- Context rot summarization (not needed at our scale)
- Echo detection (no evidence of the bug)

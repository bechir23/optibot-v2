# Real-Time Production Item List

This list is for the active LiveKit voice path, not fallback-only testing.

## Verified Now

- LiveKit cloud deployment from the current tree succeeds.
- Real provider smoke succeeds for Cartesia TTS, Deepgram STT, AMD classification, and hold lifecycle.
- Session state now persists and restores across restarted sessions.
- A real LiveKit room probe script exists at [tests/e2e_livekit_room_probe.py](/C:/Users/bechi/optibot-v2/tests/e2e_livekit_room_probe.py).
- Outbound jobs now explicitly connect to the LiveKit room, and fresh room probes confirm the agent joins as a participant.
- End-call behavior now waits for the goodbye speech to finish before shutting the session down, with room cleanup delegated to session close.

## Highest-Priority Remaining Gaps

1. Real joined-room validation is still too manual.
Reason:
- The current real-time probe creates a real room and URL, but we still need a repeatable human-in-the-loop or media-injection script for live turn-taking, hold music, and resume behavior.

2. Tool-loop discipline still needs one more pass in the live path.
Reason:
- The real LLM conversation smoke now triggers tools and extraction reliably, but the live path previously hit the max tool-step ceiling near turn end.
- Community reports repeatedly flag uncontrolled tool retries as a real production risk, so the next pass should add stricter completion and loop-stop guardrails.

3. Hold-music validation is still phrase/state-driven, not real audio-driven.
Reason:
- The hold detector is working better, but we still are not piping actual hold audio into a joined LiveKit room from automation.

4. Interruption tuning is still conservative and needs live-room calibration.
Reason:
- LiveKit exposes adaptive interruption and false-interruption controls, and production feedback consistently shows short acknowledgements and hold music are common failure modes.
- We still need a room-level script to validate barge-in, false interruption recovery, and resume behavior with real audio.

5. Redis-backed statefulness still needs a live environment check.
Reason:
- Local Redis was unavailable/open-circuit during smoke, so tenant isolation and live active-call checks were skipped.

6. Local observability validation is still environment-sensitive.
Reason:
- `/metrics` and `/health` checks depend on the local API server actually running.
- The cloud agent deploy path and the local FastAPI path need explicit test separation.

## Real-Time Test Matrix To Add

- Normal reimbursement conversation with identification, status, timeline, and reference extraction.
- Human says `je verifie`, pauses, comes back, and the agent resumes once.
- True hold phrase followed by silence/hold audio and then human return.
- Short barge-in while the agent is speaking.
- IVR to human handoff with preserved context.
- Disconnect and reconnect with restored session state.
- AMD edge cases:
  - short `allo`
  - long voicemail greeting
  - dead air / no answer
- SIP failure classes:
  - busy
  - declined
  - unavailable
  - auth/provider failure

## Repo Changes Still Worth Doing

- Add a room-joined media injection harness for replaying French speech and hold audio into LiveKit.
- Add a scripted joined-room scenario runner that verifies agent presence, greeting, hold suppression, human return, tool usage, and clean hangup in one flow.
- Add explicit loop-stop policy when the same information request or tool intent repeats without new evidence.
- Add explicit orchestration metrics for handoff loops, restore events, AMD outcomes, and context-loss incidents.
- Split local HTTP health/metrics checks from deployed-agent checks in the smoke scripts.
- Add a production French conversation policy source instead of spreading phrasing logic across prompt, naturalizer, and response queue.
- Decide whether `llm.py` remains as offline-only utility or should be removed.

## Telnyx Integration Reality Check

- Current repo usage is SIP-trunk-only through LiveKit:
  - [main.py](/C:/Users/bechi/optibot-v2/app/main.py) dials with `ctx.api.sip.create_sip_participant(...)`.
- The runtime consumes a LiveKit outbound trunk ID. Historically this repo used `TELNYX_SIP_TRUNK_ID` for that value, but the safer/current name is `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`.
- `TELNYX_API_KEY` is still not used anywhere in the active call path.
- Implication:
  - We do not currently have direct Telnyx Call Control webhooks, `call_control_id`, Telnyx-native AMD modes, media forking, or Telnyx transfer/hangup/gather actions in our app.
  - Telnyx docs about Voice API and Call Control are useful architecture references, but not active behavior in this repo until we add a webhook/control-plane integration.
- Portal-side settings that still matter even in the current SIP-trunk model:
  - codec priority including `G.722` fallback to `G.711`
  - jitter buffer tuning
  - bidirectional noise suppression
  - outbound voice profile channel limits / routing
- If we want tighter telephony control than LiveKit SIP currently gives us, the next architectural fork is explicit:
  - stay on LiveKit SIP and improve room/session behavior there, or
  - add a direct Telnyx Voice API / Call Control path for webhook-driven call state and richer PSTN controls.

## Research Notes

Official guidance used:

- LiveKit sessions and `userdata`: https://docs.livekit.io/agents/build/sessions
- LiveKit job lifecycle / participant wait: https://docs.livekit.io/agents/worker/job/
- LiveKit handoffs and context preservation: https://docs.livekit.io/agents/logic/agents-handoffs/
- LiveKit turn detection and interruption controls: https://docs.livekit.io/agents/v1/build/turn-detection
- LiveKit adaptive interruption handling: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling
- LiveKit Cloud observability/insights: https://docs.livekit.io/deploy/observability/insights/
- Deepgram Nova-3 to Flux guidance: https://developers.deepgram.com/docs/flux/nova-3-migration
- Telnyx Programmable Voice overview: https://developers.telnyx.com/docs/voice/programmable-voice
- Telnyx Voice API webhooks: https://developers.telnyx.com/docs/voice/programmable-voice/voice-api-webhooks/
- Telnyx AMD: https://developers.telnyx.com/docs/voice/programmable-voice/answering-machine-detection
- Telnyx SIP jitter buffer: https://developers.telnyx.com/docs/voice/sip-trunking/features/jitter-buffer
- Telnyx SIP noise suppression: https://developers.telnyx.com/docs/voice/sip-trunking/features/noise-suppression
- Telnyx external transfers: https://developers.telnyx.com/docs/voice/sip-trunking/features/external-transfers

Relevant community signals:

- LiveKit Python examples: https://github.com/livekit-examples/python-agents-examples
- LiveKit agent demos including telephony patterns: https://github.com/livekit-examples/agent-demos
- LiveKit core agents repo: https://github.com/livekit/agents
- Tool-loop failure mode in production: https://www.reddit.com/r/AI_Agents/comments/1r9cj81/our_ai_agent_got_stuck_in_a_loop_and_brought_down/
- Voice-agent latency and retrieval complaints in production: https://www.reddit.com/r/AI_Agents/comments/1r1bdzn/anyone_building_production_ai_voice_agents/

Community and forum searches were used to look for repeated complaints around interruptions, context loss, and hold behavior, but the indexed results were noisy. The engineering decisions in this repo are therefore grounded primarily in official LiveKit docs, Deepgram docs, and the published example repositories above.

## Current Recommendation

The next pass should focus on real joined-room evaluation, not more text-only fallback smoke.

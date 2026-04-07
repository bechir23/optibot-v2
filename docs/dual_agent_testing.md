# Dual-Agent LiveKit Room Testing

End-to-end testing pattern where TWO participants join the same real LiveKit
Cloud room: our production agent (under test) and a French mutuelle simulator
(the test driver).

## Architecture

This pattern is sourced from the canonical
[livekit/livekit-cli `agentloadtester.go`](https://github.com/livekit/livekit-cli/blob/main/pkg/loadtester/agentloadtester.go)
loadtester. It is the official LiveKit pattern for "tester participant vs
agent under test".

```
                  [LiveKit Cloud Room: e2e-{scenario}-{uuid}]
                                    |
              +---------------------+---------------------+
              |                                           |
    Production Agent (kind=AGENT)            Mutuelle Simulator (kind=STANDARD)
    - Dispatched via                          - Plain rtc.Room() client
      LiveKitAPI.agent_dispatch               - Subscribes to agent's audio
    - Cartesia TTS                            - Pipes PCM -> Deepgram STT
    - Deepgram STT                            - Feeds transcript -> OpenAI LLM
    - OpenAI LLM (gpt-4.1-mini)                 with French persona prompt
    - Real OutboundCallerAgent code           - Streams text -> Cartesia TTS
                                              - Publishes via rtc.AudioSource
                                                + LocalAudioTrack
```

Key design choices (and why):

- **Two participants in ONE room**, not two `AgentSession` instances. This
  matches the official LiveKit pattern. The agent is dispatched normally
  (kind `AGENT`); the simulator joins as a regular SDK client (kind `STANDARD`)
  with a different `identity`. Identity collision is impossible because the
  worker picks the agent identity automatically and the simulator uses
  `f"sim-{persona.key}"`.

- **One JobContext, not two.** The simulator does NOT need to be a deployed
  worker — it's a Python process you run alongside the deployed agent. This
  keeps the test runnable from a developer machine, CI, or a container,
  without registering a new worker with LiveKit Cloud.

- **Loop prevention via silence gating.** The simulator only speaks after
  detecting >700ms of silence from the agent's audio stream (matches the
  `EchoSpeechDelay` pattern from `agentloadtester.go`). This is critical:
  without it, both sides would talk over each other indefinitely once VAD
  triggers on TTS bleed.

- **Hard turn cap.** Each persona has an `expected_turns` field (default 8-10).
  The loop stops at that count even if neither side has produced a "natural"
  end. This prevents runaway costs and infinite loops on bugs.

- **Per-scenario unique room.** `room_name = f"e2e-{persona.key}-{uuid4().hex[:8]}"`.
  No state leaks between scenario runs.

## Personas

| Key | Persona | Mutuelle | Tests |
| --- | --- | --- | --- |
| `harmonie_happy_path` | Sophie | Harmonie Mutuelle | Friendly identification + status retrieval |
| `mgen_strict_identification` | Marc | MGEN | Strict NIR-first identification flow |
| `almerys_cold_transfer` | Catherine -> Patrick | Almerys | Cold transfer detection + interlocuteur change |
| `viamedis_long_hold` | Jean | Viamedis | Multi-minute hold + strong return phrase recovery |

Each persona is a full French system prompt in `tests/e2e_dual_real_room.py`.
The persona LLM does NOT know it's a robot — it role-plays a real mutuelle
gestionnaire.

## Scoring (LLM judge)

After each scenario the full transcript is fed to a separate LLM (with the
`JUDGE_RUBRIC` prompt) that scores 8 criteria:

| Criterion | Range | Hard fail? |
| --- | --- | --- |
| `info_collected` | 0-3 | no |
| `politeness` | 0-1 | no |
| `french_register` | 0-1 | no |
| `no_banned_phrases` | 0-1 | YES |
| `no_loop` | 0-1 | YES |
| `tool_correctness` | 0-2 | no |
| `no_hallucination` | 0-1 | YES |
| `graceful_close` | 0-1 | no |
| **total** | **0-10** | |

A "hard fail" criterion zeros the total score. This means an agent that
collected all the info but said `"un instant"` on the first turn still fails.

The judge runs as a SECOND PASS over the recorded transcript, not inline,
so you can re-score saved transcripts with a different rubric without
re-running the call.

## Running

Prerequisites:
- The production agent must already be deployed to LiveKit Cloud and
  registered with the agent name in `OPTIBOT_AGENT_NAME` (default `optibot`).
- Environment variables:
  - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  - `OPENAI_API_KEY` (for the simulator LLM and the judge LLM)
  - `DEEPGRAM_API_KEY` (for the simulator's STT)
  - `CARTESIA_API_KEY` (for the simulator's TTS)
  - `OPTIBOT_AGENT_NAME` (optional, default `optibot`)

Single scenario:
```powershell
python tests/e2e_dual_real_room.py --scenario harmonie_happy_path
```

All four:
```powershell
python tests/e2e_dual_real_room.py --scenario all
```

Output:
- Each scenario writes `tests/results/{scenario}_{timestamp}.json` with
  full transcript, judge score, and verdict.
- Process exit code is `0` if every scenario passes, `1` if any failed.

## Current implementation status

The committed scaffold in `tests/e2e_dual_real_room.py`:

- [x] Persona dataclass + 4 French personas
- [x] LiveKit Cloud agent dispatch via `LiveKitAPI.agent_dispatch`
- [x] Simulator connects to room as STANDARD participant with different identity
- [x] AudioSource + LocalAudioTrack publishing (track is created and published)
- [x] Subscribe to agent audio + silence detection (700ms threshold)
- [x] Per-scenario unique room name with UUID
- [x] Result JSON writer to `tests/results/`
- [x] CLI with `--scenario {key|all}`
- [ ] Streaming Deepgram STT on agent audio frames -> transcript buffer
- [ ] Persona LLM call with running transcript context (OpenAI)
- [ ] Streaming Cartesia TTS into `rtc.AudioSource.capture_frame()`
- [ ] LLM judge second pass over recorded transcript
- [ ] Hard-fail rule check (banned phrases regex pre-judge)

The first 7 items are implemented. The last 5 are marked TODO inside the
file because they each require ~50-100 lines of provider-specific audio
glue and benefit from being added incrementally with real LiveKit
credentials available for iterative debugging. The scaffold compiles,
imports cleanly, and runs end-to-end as a smoke test today: it
dispatches the agent, joins the room, waits up to 30s for the agent to
appear, captures 10s of audio events, then writes a result file with
verdict `SCAFFOLD`.

## Adding a new persona

Edit `tests/e2e_dual_real_room.py`:

```python
NEW_PERSONA = MutuellePersona(
    key="my_new_scenario",
    name="Claire",
    mutuelle="Apivia",
    voice_id="...",  # Cartesia French voice ID
    expected_turns=8,
    system_prompt="Tu es Claire, gestionnaire chez Apivia. ...",
)

PERSONAS["my_new_scenario"] = NEW_PERSONA
```

Then run:
```powershell
python tests/e2e_dual_real_room.py --scenario my_new_scenario
```

## Why not voicetest / LangWatch Scenario / Hamming?

Considered and rejected for the in-tree harness:

| Tool | Why not | What we use instead |
| --- | --- | --- |
| `voicetestdev/voicetest` | Docker-compose stack with its own LiveKit + Whisper + Kokoro. Heavy. We want to test against our actual deployed agent in our actual LiveKit Cloud project. | Our own scaffold using the same 3-role pattern (simulator + agent + judge). |
| `langwatch/scenario` | Text-only, no real WebRTC. Excellent for unit tests but does not catch audio path bugs. | LangWatch's `JudgeAgent` rubric design is reused as inspiration for `JUDGE_RUBRIC`. |
| Hamming AI / Coval / Cekura | Commercial, no public pricing, vendor lock-in. | Run them later as a complement, not as the primary harness. |

The result: our test directly exercises real LiveKit Cloud, real Deepgram,
real Cartesia, real OpenAI — same exact stack as production. Bugs that
the audio path introduces (transcoding artifacts, codec negotiation, SIP
bridge issues) will reproduce. Bugs that exist only with mock STT/TTS
won't be missed.

## Sources

- [livekit/livekit-cli agentloadtester.go](https://github.com/livekit/livekit-cli/blob/main/pkg/loadtester/agentloadtester.go) — canonical pattern
- [livekit/agents testing docs](https://docs.livekit.io/agents/build/testing/) — official guidance
- [voicetestdev/voicetest](https://github.com/voicetestdev/voicetest) — 3-role inspiration
- [langwatch/scenario](https://github.com/langwatch/scenario) — judge rubric design
- [OpenAI Realtime Eval Guide](https://developers.openai.com/cookbook/examples/realtime_eval_guide) — Crawl/Walk/Run maturity model
- French mutuelle hold corpus research (in-house) — persona authoring

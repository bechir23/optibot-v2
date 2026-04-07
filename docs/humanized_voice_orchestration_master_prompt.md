# Humanized Voice Orchestration: Architecture, Backlog, and Claude Master Prompt

## 1) Target Outcome

Build a production voice system that behaves like a skilled human call operator:

- Maintains context across turns, handoffs, and call restarts.
- Speaks naturally in fluent French without repetitive canned wording.
- Knows when to talk, when to wait, when to interrupt, and when to stay silent.
- Handles AMD, SIP, IVR, and telephony edge cases without losing memory.
- Stays low-latency and observable under load.


## 2) Recommended Architecture (for this repo)

Use a hybrid model:

- Real-time path: Single active call agent with strict tool controls (lowest latency).
- Parallel specialist analysis path: bounded background specialist agents for hard turns.
- Supervisor router: promotes to specialist fan-out only when complexity threshold is met.

Why this architecture:

- Full multi-agent for every turn adds latency and failure modes.
- Single-agent only is simpler but weak on complex negotiation and robustness.
- Hybrid gives human-like speed on simple turns and deeper reasoning on complex ones.


## 3) Agent Roles and Boundaries

### 3.1 SupervisorRouter

Responsibilities:

- Detect turn complexity and route strategy.
- Enforce loop limits, timeout budget, and escalation policy.
- Select pattern: direct, handoff, or parallel fan-out/fan-in.

Allowed tool domains:

- call_control
- observability_ops
- policy_checks


### 3.2 CallConductor (primary live voice agent)

Responsibilities:

- Real-time dialog and negotiation with mutuelle.
- Maintain conversational coherence and short replies.
- Trigger memory checkpoints every significant turn.

Allowed tool domains:

- patient_info
- reimbursement_actions
- call_control
- memory_ops


### 3.3 IVRSpecialist

Responsibilities:

- DTMF navigation and menu strategy.
- Transfer reasoning with path evidence.
- Pass compact IVR transcript to CallConductor on handoff.

Allowed tool domains:

- telephony_ops
- call_control
- memory_ops


### 3.4 MemoryKeeper

Responsibilities:

- Checkpoint state and summaries per turn.
- Compact context for token budgets.
- Persist cross-call mutuelle learnings.

Allowed tool domains:

- memory_ops
- observability_ops


### 3.5 ComplianceGuard

Responsibilities:

- PII disclosure policy checks.
- Prompt-policy consistency checks.
- Redaction and disclosure gating.

Allowed tool domains:

- compliance_ops
- policy_checks


### 3.6 RecoveryAgent

Responsibilities:

- Fallback behavior when STT/LLM/TTS or provider fails.
- Graceful degradation messages.
- Retry/circuit-breaker-safe recovery paths.

Allowed tool domains:

- call_control
- telephony_ops
- observability_ops


## 4) Orchestration Patterns to Apply

Use pattern by situation:

- Default: Single agent with tools.
- Dynamic specialist transfer: Handoff pattern.
- Parallel for complex high-value turns: Concurrent fan-out/fan-in.
- Quality gate for risky outputs: Maker-checker loop (max iteration cap).

Hard guardrails:

- Max handoff depth.
- Max parallel specialists per turn.
- Max iteration count for checker loops.
- Timeout and fallback at every boundary.


## 5) Context and Memory Design

Short-term state (per call):

- Redis call state plus structured turn log.
- Turn checkpoints every meaningful update.
- Full IVR and hold timeline preserved.

Long-term state (cross-call):

- Mutuelle memory snapshots with versioned summaries.
- Outcome-linked learnings, not raw transcript bloat.
- Action success rates persisted and queryable.

Compaction strategy:

- Full context is never forwarded blindly.
- Each handoff receives:
  - fixed schema summary
  - unresolved goals
  - latest evidence
  - safety flags


## 6) Humanized Conversation Policy

Do not hardcode tiny filler lists.

Use policy-driven generation:

- Natural short acknowledgments with anti-repeat logic.
- Backchannel support without false interruption.
- Silence policy:
  - stay silent during explicit hold/wait phrases
  - timed keepalive only when needed
- Post-hold re-entry utterance always emitted.

French quality policy:

- Force French locale for STT/TTS + phrase-level checks.
- Block unnatural mixed-language outputs.
- Apply pronunciation and pacing normalization before TTS.


## 7) Responsiveness and Audio Policy

Latency budget targets (turn-level):

- STT finalization: <= 800ms target
- LLM first token: <= 1200ms target
- TTS start: <= 600ms target after text

Turn-taking controls:

- Adaptive endpointing by context.
- Stop-speaking plan tuned to avoid interrupting short user acknowledgments.
- Immediate cancellation path for true user interruption.

Audio quality controls:

- Echo mitigation profile by participant kind.
- Voice provider fallback for degraded quality.
- Speaking-rate bounds to prevent too-slow synthesis.


## 8) Priority Backlog (Mandatory)

## P0 (Immediate)

1. Wire response queue and naturalizer into active runtime path.
2. Fix hold-ended silence gap with guaranteed re-entry response.
3. Persist extracted data checkpoints before final call end.
4. Preserve full IVR transcript context at handoff.
5. Add strict timeout/fallback around LLM turn generation.
6. Remove deceptive identity instruction and replace with compliant transparency.

## P1

7. Refresh RAG context on strategic call milestones.
8. Convert hardcoded filler behavior to policy + variation source.
9. Promote durable-write failures from debug to error with metrics.
10. Make SIP retry strategy configurable per tenant/mutuelle profile.

## P2

11. Add bounded specialist parallel fan-out for complex turns.
12. Add maker-checker quality gate for high-risk outputs.
13. Add orchestration-level dashboards (handoff loops, retries, fallback rates).


## 9) Acceptance Criteria

- Context continuity survives IVR->human handoff and disconnect/reconnect.
- No repetitive canned loop in a 20-turn simulated call.
- French fluency score above threshold in test corpus.
- P95 turn latency stays within budget.
- All persistence-critical paths have retry + alerting.
- No unresolved dead paths for memory/orchestration modules.


## 10) Master Prompt for Claude (Copy/Paste)

You are the lead engineer for this repository and must implement a production-grade humanized voice-call orchestration system.

Primary objective:
Transform the current voice agent into a context-persistent, low-latency, fluent-French, human-like call operator with robust telephony handling.

Execution mode:

0. First step: inventory all available tools, subagents, and MCP integrations in the current runtime; explicitly list what is available vs unavailable before coding.
1. Use all available local tools and subagents in parallel where independent.
2. Prefer concrete code and tests over abstract architecture text.
3. Do not hallucinate dependencies or APIs. Verify in-repo and in docs before changing.
4. Keep changes minimal but complete for each milestone.

Evidence requirements before major code changes:

- Fetch and use current docs for LiveKit, Anthropic/Claude tools, Telnyx/Twilio telephony, and at least one orchestration framework (LangGraph, LangChain, CrewAI, or equivalent).
- Run repository-wide checks for dead paths, hidden services, prompt-policy contradictions, and persistence gaps.

Required implementation tracks:

Track A: Runtime Orchestration

- Implement a SupervisorRouter strategy in existing flow.
- Keep single-agent real-time path for most turns.
- Add bounded specialist parallel fan-out only for complex turns.
- Add handoff loop guards and iteration caps.

Track B: Context and Memory

- Ensure per-turn checkpoint persistence (not only finalization).
- Preserve IVR transcript + state on handoff.
- Add compact summary handoff schema.
- Persist long-term mutuelle learnings safely.

Track C: Humanized Conversation

- Replace hardcoded repetitive filler behavior with policy-based variation.
- Guarantee post-hold re-entry utterance.
- Enforce fluent French generation and pronunciation normalization.
- Tune speaking responsiveness: interrupt handling, wait timing, resume timing.

Track D: Telephony Robustness

- Improve AMD and SIP handling paths with configurable policy.
- Add clear fallback behavior for not_sure and provider error classes.
- Add escalation-to-human gates for unresolved states.

Track E: Reliability and Observability

- Add timeout/retry/circuit-breaker-safe behaviors for external dependencies.
- Raise durable-write failures as error-level events.
- Add metrics for handoffs, interruption cancels, fallback invocations, and context-loss incidents.

Track F: Tests and Validation

- Add/expand tests for response queue wiring and hold behavior.
- Fix async test patterns for Python 3.12 compatibility.
- Add integration-level flow tests for handoff context continuity.
- Run lint + tests and report exact residual failures.

Repo-focused constraints:

1. Do not rewrite the platform architecture from scratch.
2. Preserve LiveKit session flow and existing telephony primitives.
3. Prefer extending existing modules before creating new top-level subsystems.
4. Keep API compatibility unless a breaking change is explicitly justified.

Mandatory quality bars:

- No dead code path left for key orchestration modules.
- No silent failure for persistence-critical operations.
- No deceptive identity instruction in prompts.
- No infinite handoff/tool loops.

Output format for each milestone:

1. What changed (files + behavior).
2. Why it changed.
3. Test evidence.
4. Remaining risks and next step.

Start now with P0 items in this order:

1. Hold-ended response behavior.
2. Context persistence checkpoints.
3. IVR handoff context continuity.
4. Timeout and fallback hardening.
5. French humanization policy wiring.

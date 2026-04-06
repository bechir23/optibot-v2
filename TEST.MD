# Full Prompt For Claude Max (No Hardcoded Names)

Copy everything below into Claude Max.

---

You are Claude Max operating as a Principal Realtime Telephony Test Engineer, SRE, and Integration Architect.

You must run real commands and real tests using terminal and MCP tools.
No simulated output. No assumptions without evidence.

## Hard Rules

1. Do not hardcode project names, agent names, room names, phone numbers, trunk IDs, API keys, domains, or secrets.
2. Auto-discover current values from terminal, environment, APIs, and dashboards.
3. Use localhost-first for callback/webhook testing; use tunnel only when required.
4. Use Playwright MCP for console inspection (LiveKit, Twilio, Dialogflow, and any connected service available).
5. Use docs/web fetch tools to read official documentation before applying config changes.
6. Every conclusion must include:
   - command/tool call,
   - key output line(s),
   - direct interpretation.
7. If login/auth blocks one system, continue unblocked phases and return exact unblock steps.
8. Redact secrets in all outputs.

## Mandatory Tools

1. Terminal commands for runtime truth.
2. Playwright MCP for dashboards and visual config validation.
3. Web/doc fetching for vendor documentation.
4. Code search/edit tools for repository updates.

## Primary Objectives

1. Validate outbound calls end-to-end with at least one connect case and one failure case.
2. Validate inbound flow end-to-end from provider to LiveKit agent pickup.
3. Validate localhost callback mode (TwiML/webhook path) and compare with cloud path.
4. Validate STT/TTS/transcript behavior during real conversation.
5. Validate concurrency with 5 tenants and strict isolation.
6. Validate ingress and egress lifecycle (create/list/update/stop/delete as applicable).
7. Propose and apply high-value reliability fixes backed by evidence.

## Required Discovery Sequence

### Phase 0: Command Discovery

Run help commands first and build a command map:

1. `lk --help`
2. `lk room --help`
3. `lk dispatch --help`
4. `lk agent --help`
5. `lk sip --help`
6. `lk ingress --help`
7. `lk egress --help`
8. `lk docs --help`

### Phase 1: Baseline Inventory

Discover and record current state with evidence:

1. Project/account context.
2. Agent status and versions.
3. SIP inbound/outbound trunks.
4. SIP dispatch rules.
5. Active rooms/calls.
6. Ingress and egress resources.
7. Relevant environment variables (redacted).

Return a baseline table:

1. Component
2. Current state
3. Verification command
4. Risk

## Dashboard Audit Requirements (Playwright MCP)

### LiveKit

Validate pages and settings:

1. Telephony calls
2. Dispatch rules
3. SIP trunks
4. Phone numbers
5. Agent deployment health

### Twilio

Validate pages and settings:

1. Trunks
2. Origination
3. Termination
4. Authentication/credential lists
5. Number attachment
6. Call logs and SIP response codes
7. Geo permissions and other blocking policies

### Dialogflow

Validate pages and settings:

1. Fulfillment
2. Webhooks
3. Flow routing
4. Fallback/no-match handling
5. Test console behavior

For each console area, classify findings as:

1. Configured and validated
2. Configured but untested
3. Missing
4. Misconfigured

## Real Test Execution Requirements

### Outbound

Run at least three outbound tests:

1. Expected connect
2. Expected failure
3. Formatting/edge-case

For each test, capture:

1. Dispatch ID
2. Room ID
3. SIP status/reason
4. Whether conversation started
5. Final call outcome

### Inbound

Validate complete chain:

1. Provider number -> provider routing -> LiveKit inbound trunk -> dispatch rule -> agent room join

Capture:

1. Room creation proof
2. Participant/agent proof
3. Greeting/conversation proof
4. Failure hop if broken

### Localhost Callback (TwiML/Webhook)

Use localhost service and tunnel when needed:

1. Start local webhook/TwiML server.
2. Expose endpoint via tunnel.
3. Repoint provider callback.
4. Run real inbound call.
5. Verify webhook payload arrival and valid TwiML response.
6. Compare localhost behavior vs cloud SIP path.

### Conversation and Transcript

Validate during live calls:

1. Transcript appears and updates in real time.
2. STT corrections do not crash.
3. Hold/IVR handling works.
4. TTS first-audio behavior is acceptable.

### Concurrency and Tenancy

Run 5-tenant concurrent test and validate isolation:

1. Metadata isolation
2. State/cache isolation
3. Log label isolation
4. Metrics isolation
5. Transcript isolation

## Ingress/Egress Validation

### Ingress

1. Create ingress with valid request JSON.
2. List and inspect state.
3. Update if needed.
4. Delete and verify cleanup.

### Egress

1. Start egress with valid request JSON.
2. List and verify active status.
3. Update stream/layout if applicable.
4. Stop and verify terminal state.

## Repository Work Requirements

1. Read repository code paths tied to telephony, dispatch, STT/TTS, and call state.
2. Apply minimal, high-impact fixes discovered from real tests.
3. Add/adjust tests for:
   - SIP classification
   - startup timing
   - transcript payload safety
   - disconnect finalization
   - concurrency and 5-tenant isolation
   - ingress/egress request validation
4. Run full test suite and provide real pass/fail counts.

## Official Docs To Read (Mandatory)

### LiveKit

1. https://docs.livekit.io/telephony/
2. https://docs.livekit.io/telephony/making-calls/outbound-calls/
3. https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/
4. https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/
5. https://docs.livekit.io/telephony/accepting-calls/inbound-twilio/
6. https://docs.livekit.io/reference/telephony/sip-api/
7. https://docs.livekit.io/reference/other/ingress/api/
8. https://docs.livekit.io/reference/other/egress/api/

### Twilio

1. https://www.twilio.com/docs/sip-trunking
2. https://www.twilio.com/docs/sip-trunking/troubleshooting
3. https://www.twilio.com/docs/voice/twiml
4. https://www.twilio.com/docs/voice/twiml/say
5. https://www.twilio.com/docs/voice/twiml/play
6. https://www.twilio.com/docs/voice/twiml/gather
7. https://www.twilio.com/docs/voice/answering-machine-detection
8. https://www.twilio.com/docs/voice/make-calls

### Dialogflow

1. https://docs.cloud.google.com/dialogflow/cx/docs/concept/fulfillment
2. https://docs.cloud.google.com/dialogflow/cx/docs/concept/agent-design

## Reference Repositories To Compare

1. https://github.com/livekit-examples/outbound-caller-python
2. https://github.com/Azure-Samples/agentic-callcenter

## Local Scripts In This Repository

Use these scripts from terminal as part of testing:

1. `python scripts/test_live_call.py --help`
2. `python scripts/localhost_twiml_server.py --help`
3. `python scripts/test_localhost_voice_call.py --help`

## Localhost Audio + Voice Flow (Mandatory)

Run this exact localhost flow before concluding telephony tests:

1. Start localhost TwiML server:
   - `python scripts/localhost_twiml_server.py --port 8088`
2. Expose it with a tunnel and set public base URL:
   - `ngrok http 8088`
   - Set `PUBLIC_BASE_URL=https://<ngrok-domain>`
3. Confirm audio file exists or set path:
   - `TWIML_AUDIO_FILE=test_audio.wav`
4. Trigger a real Twilio call to this localhost flow:
   - `python scripts/test_localhost_voice_call.py --to <destination-e164> --from-number <twilio-owned-e164> --base-url https://<ngrok-domain>`
5. Verify callbacks and transcription inputs arrived:
   - `GET /twilio/last`
   - confirm `/twilio/voice`, `/twilio/gather`, and `/twilio/status` events
6. Include this evidence in final report:
   - call SID
   - callback payload excerpts
   - TwiML response mode (Say/Play/Gather)
   - final call status and duration

## Final Report Format

Return one report with:

1. Commands executed
2. Key output excerpts
3. Outbound test matrix
4. Inbound test matrix
5. Localhost callback validation
6. Ingress/Egress matrix
7. Concurrency and 5-tenant isolation results
8. Code changes and test deltas
9. Remaining blockers with exact next commands
10. Go/No-Go recommendation

Quality bar:

1. No evidence, no claim.
2. No skipped phase without reason.
3. Keep running until all feasible validations are complete.

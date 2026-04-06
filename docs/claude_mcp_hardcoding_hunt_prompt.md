# Claude One-Shot Prompt: MCP Hardcoding Hunt + Real-Time Dynamic Config

Use this exact workflow and do not skip search/fetch steps.

## Goal
Find all hardcoded runtime knowledge in this repository, compare with production patterns from external repos, and implement a real-time dynamic config architecture with safe reload semantics.

## Phase 1: Mandatory local repo search
Run local search first and produce a hotspot inventory before coding.

Required query classes:
1) static vocab and constants
- ^[A-Z_]{3,}\s*[:=].*(\{|\[)
- _FALLBACK_|DEFAULT|hardcoded

2) regex and text normalization rules
- re\.compile\(
- ABBREVIATIONS|KNOWN_MUTUELLES|ALIASES|PATTERN

3) provider/model literals
- (openai|deepgram|cartesia|mistral|groq|gpt-|sonic-|nova-)

4) env defaults and startup-only loading
- os\.getenv\([^\)]*,\s*['"][^'"]+['"]
- load\(|refresh|watch|sentinel

Output requirement:
- At least 20 hotspots with path, line, why-hardcoded, and impact.

## Phase 2: Mandatory external fetch
Fetch concrete implementation references from at least 3 families:
- LiveKit agents/examples
- Azure App Configuration dynamic refresh/sentinel patterns
- Supabase/Postgres RLS and performance practices

Rules:
- At least 12 external references total.
- At least 4 references must be code-level files (not only docs pages).
- If raw URL fails, fetch repo tree/readme then locate valid file paths.
- Log failed URLs and successful fallback URLs.

## Phase 3: Architecture mapping
Propose architecture only after Phases 1 and 2 are complete.

Must include:
- Source priority: DB -> file -> env -> minimal fallback
- atomic snapshot activation
- last-good snapshot retention
- validation pipeline for regex/pattern sets
- background refresh cadence + sentinel/version trigger
- observability metrics and health fields

## Phase 4: Implementation
Implement ConfigRegistry and integrate into runtime.

Mandatory implementation properties:
- no partial snapshot reads
- no call-path blocking during refresh
- graceful failures preserve last-good config
- explicit metrics for reload status/version/duration

## Phase 5: Validation
Required checks:
- unit tests for merge priority
- unit tests for invalid regex rejection
- unit tests for live reload behavior
- regression tests for STT and SSML correctness
- deployment sanity checklist (local compose + cloud worker)

## Final output format
1) Search and fetch log
- local queries
- fetched URLs
- failed URLs and fallback actions

2) Hardcoding debt report
- resolved items
- remaining hardcoded items with justification or follow-up task

3) Code change summary
- file-by-file changes and rationale

4) Verification
- test results
- health and observability proof points

5) Rollback plan
- exact rollback steps and trigger conditions

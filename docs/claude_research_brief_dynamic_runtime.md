# Claude Research Brief: Remove Hardcoded Runtime Knowledge and Support Real-Time Dynamic Config

## Mission
Analyze this voice-agent codebase and comparable production repositories, then design and implement a production-safe architecture where mutuelle knowledge, STT correction rules, SSML dictionaries, and normalization patterns are not hardcoded in Python modules.

The target is real-time deployability: updates must be possible at runtime with minimal restart impact, and safe fallback behavior when dynamic sources are unavailable.

## Why this is critical
Current behavior still contains static fallback dictionaries and static startup-loaded inventories in multiple modules. This creates risk:
- Slow content updates (code changes instead of config updates)
- Drift between STT normalization, fuzzy matching, and SSML normalization
- Environment inconsistency between local, docker, and cloud worker deployments
- No guaranteed real-time refresh contract

## Current code evidence to inspect
- app/pipeline/stt_correction.py
  - Dynamic loading exists, but fallback dictionaries remain in code.
  - Startup load from file/env only, no DB refresh loop.
- app/pipeline/fuzzy_matching.py
  - Dynamic list build exists, but fallback list remains in code.
- app/pipeline/ssml_normalizer.py
  - Dynamic loading exists, but fallback abbreviations/patterns/months remain in code.
- data/schema.sql
  - Newly added dynamic tables:
    - mutuelle_aliases
    - ssml_abbreviations
    - ssml_regex_patterns
    - ssml_month_names

## Production problem statement
Design a single-source-of-truth runtime config pipeline for:
1) Canonical mutuelle list
2) Alias graph for STT normalization and fuzzy matching
3) SSML abbreviation map
4) SSML regex pattern map
5) Month dictionary

The design must support:
- Priority order and deterministic merges
- Validation and rejection of malformed regex
- Atomic version switch for readers
- Graceful fallback when source unavailable
- Observability of reload success/failure and active version

## What to research in external repos (using MCP)
Find concrete patterns and reference implementations for:
1) Dynamic config refresh with sentinel keys and polling windows
2) In-memory atomic swap of config snapshots
3) Runtime cache invalidation strategy for real-time workloads
4) Validation pipeline before activating new regex/pattern sets
5) Rollback strategy for bad config pushes
6) Multi-tenant config isolation with RLS and performance-safe policies

Minimum reference families:
- LiveKit real-time agent examples and deployment patterns
- Azure App Configuration dynamic refresh patterns (sentinel key approach)
- Supabase/Postgres RLS + performance best practices for policy-heavy tables

## Mandatory MCP Search And Fetch Protocol
You must execute this protocol before proposing architecture or writing code.

1) Local hardcoding hunt in this repo
- Run broad code search for hardcoded runtime knowledge and literal inventories.
- Required local patterns (minimum):
  - Uppercase vocab dictionaries/lists: `^[A-Z_]{3,}\s*[:=].*(\{|\[)`
  - Regex literals: `re\.compile\(`
  - Hardcoded model/provider strings: `(openai|deepgram|cartesia|mistral|groq|gpt-|sonic-|nova-)`
  - Hardcoded defaults: `DEFAULT|fallback|_FALLBACK_`
  - Static environment defaults: `os\.getenv\([^\)]*,\s*['\"][^'\"]+['\"]`
- Output minimum 20 local hotspots with file paths and reasons.

2) External repo fetch and evidence extraction
- Fetch at least 12 concrete references across at least 3 repo families.
- Include at least 4 references that show runtime refresh patterns (sentinel/watch key/polling/versioned snapshots).
- Include at least 4 references that show safe config activation patterns (validation before swap, last-good fallback).
- Include at least 4 references for deployment/runtime concerns in real-time systems.

3) Fetch failure fallback procedure
- If direct raw URLs fail (404), do not stop.
- First fetch repository tree/readme pages.
- Then fetch specific file paths discovered from tree/readme.
- Record both failed URL and successful fallback URL.

4) Evidence format
- Every claim must include source and exact implementation pattern.
- Distinguish observed pattern vs proposed adaptation.
- Do not cite only top-level docs pages when code-level evidence is available.

5) Acceptance gate before implementation
- No implementation begins until:
  - local hotspot inventory complete,
  - external evidence matrix complete,
  - target architecture mapped to observed patterns.

## Required deliverables
1) Architecture doc
- Config source hierarchy (DB -> file -> env -> minimal fallback)
- Refresh mechanism and intervals
- Atomic reload strategy
- Failure mode behavior

2) Implementation
- Runtime loader service module with typed schemas
- Integration into stt_correction, fuzzy_matching, ssml_normalizer
- Optional background refresh task for worker and API processes
- Config version metric and reload outcome metrics

3) Database and migration updates
- Confirm schema for dynamic config tables
- Add indexes needed for lookup and tenant-safe filtering
- Add seed strategy and sample rows for rollout

4) Validation and tests
- Unit tests for loader merge precedence
- Unit tests for invalid regex rejection
- Unit tests for live reload behavior
- Regression tests for known phrases and no-false-positive cases

5) Deployment plan
- Local docker-compose flow
- LiveKit cloud worker flow
- Rollout phases with canary and rollback

6) Hardcoding debt report
- Enumerate all remaining hardcoded runtime knowledge after implementation.
- For each remaining hardcoded item, explain why it is acceptable or provide follow-up removal task.

## Non-negotiable acceptance criteria
- No business-critical vocab or normalization rule should require code deploy for update.
- Runtime can refresh config without process restart.
- If dynamic config fetch fails, system serves last-good snapshot.
- If no snapshot exists, minimal safe fallback used and error surfaced via metrics/logs.
- Reload errors never crash active call sessions.
- External research evidence must include code-level references, not docs-only summaries.
- Hardcoding debt report must be delivered with explicit residual risk.

## Real-time deployment constraints
- Must avoid locking the hot path in call processing.
- Snapshot reads must be O(1) and lock-minimal.
- Reload must happen off-call-thread and activate atomically.
- Per-tenant overrides must not break global defaults.

## Suggested technical direction
- Introduce a ConfigRegistry service with:
  - typed dataclasses/pydantic models for each config domain
  - last_good_snapshot + active_version
  - refresh() with validation pipeline
  - compare-and-swap activation
- Use metrics:
  - config_reload_total{status}
  - config_active_version
  - config_reload_duration_ms
  - config_validation_failures_total
- Use health endpoint extension:
  - include config source and active version age

## Security and correctness notes
- Treat regex from DB as untrusted input; compile in sandboxed validation step.
- Keep max regex complexity guardrails.
- RLS policies must include explicit role scope and indexed tenant filters.
- Do not expose service-role keys in any frontend context.

## Execution style expected
- Use MCP to inspect multiple repos and cite concrete patterns.
- Show exact files changed and reason for each.
- Provide before/after behavior examples for at least 10 STT and SSML cases.
- End with a rollback checklist.
- Include a "search and fetch log" appendix listing:
  - local search queries,
  - fetched URLs,
  - failed URLs and fallback resolution.

# Telnyx + LiveKit Configuration Runbook (France / EU)

All research in this document is sourced from official Telnyx and LiveKit
documentation, and verified GitHub issues, current as of April 2026. Every
recommendation is a portal or API configuration change — no code changes
are needed unless explicitly noted.

## Why This Matters

Research confirmed three facts that make Telnyx configuration critical for
French telephony:

1. **Telnyx Paris GPU PoP exists** with sub-200ms round-trip time for Voice AI
   Source: <https://telnyx.com/release-notes/europe-voice-ai-infra>
2. **`sip.telnyx.com` is the US default** — Telnyx uses GeoDNS so EU callers
   should still land on EU infra, but anchorsite must be explicitly set
3. **LiveKit region pinning via `destination_country="FR"`** keeps calls in-region
   Source: <https://docs.livekit.io/telephony/features/region-pinning/>

LiveKit #4053 (open) reports EU-hosted LiveKit Cloud adds ~2s per turn vs local.
Combined with a US-routed agent process, this compounds to unusable latency.

## SECURITY NOTICE: X-Telnyx-Username header is MANDATORY

Per Telnyx's official LiveKit integration guide:

> "If Telnyx finds any existing SIP IP connection from the same source IP,
> it uses that connection as the authenticated user and skips authentication
> challenges, **which could match a connection belonging to a different customer.**"

This is a **cross-customer SIP IP collision security risk**, not just a
latency optimization. On shared LiveKit Cloud infrastructure, your outbound
trunk could inadvertently use another customer's Telnyx SIP connection if
the source IPs overlap.

**Mitigation (required)**: In your LiveKit `SIPOutboundTrunk`, add the
`X-Telnyx-Username` header so Telnyx always runs digest authentication:

```json
"headers_to_attributes": {
  "X-Telnyx-Username": "YOUR_TELNYX_USERNAME"
}
```

This forces Telnyx to respond with 407 Proxy Authentication Required,
triggering the SIP digest auth flow and correctly scoping the call to
your account. Source: [Telnyx LiveKit configuration guide](https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide).

## Required Telnyx Portal Configuration

### Interpreting recent portal changes

If you have already:
- switched the Voice API application anchorsite to **Frankfurt**
- created a **SIP Connection**
- created an **Outbound Voice Profile**

then you are only partway done. Those changes are necessary, but they do
**not** by themselves make the current repo able to dial.

The runtime still needs all of the following to be true:
- the SIP Connection is fully completed with outbound auth and codec choices
- the Outbound Voice Profile is attached to the SIP Connection
- the correct numbers / destinations are enabled on the profile
- a **LiveKit outbound SIP trunk** exists and points at that Telnyx setup
- the repo env contains the **LiveKit outbound trunk ID**, not just the Telnyx portal object IDs

Important distinction:
- **Telnyx SIP Connection ID**: object created in the Telnyx portal
- **LiveKit outbound trunk ID**: object created in LiveKit and consumed by `create_sip_participant()`

This repo dials through the LiveKit outbound trunk. The Telnyx portal setup is the provider-side dependency behind it.

### 1. Anchorsite (Voice API region)

Navigate to **Voice API** > **Applications** > [your app] > **Anchorsite**

Set anchorsite to **one of**:
- `Frankfurt, Germany` (primary EU datacenter — recommended default)
- `Paris, France` (GPU PoP — preferred for French Voice AI, sub-200ms RTT)
- `Amsterdam, Netherlands`
- `London, UK`

Do **NOT** leave at default (`Latency` or US sites). The default chooses the
closest POP to the caller, which for agent-driven outbound is random.

### 2. SIP Trunk Codec Configuration

Navigate to **Real-Time Communications** > **Voice** > **SIP Trunking** >
[your trunk] > **Inbound** tab > **Codecs**

**⚠ IMPORTANT — codec choice depends on whether you need DTMF**:

#### Option A — DTMF required (IVR navigation, our use case)

- **Enable**: `G.711U` (PCMU, 8kHz) as the primary codec
- **Enable**: `G.711A` (PCMA, 8kHz) for European carriers
- **Disable or avoid**: `G.722` — research confirms **G.722 breaks DTMF**
  reliability (Telnyx docs: "DTMF is not reliable with G.722")

  Source: <https://support.telnyx.com/en/articles/3192298-audio-and-codecs>

Our `IVRNavigatorAgent` uses `press_digit()` for menu navigation. If
G.722 is enabled as the preferred codec, DTMF tones may not reach the
mutuelle's IVR. Stick with G.711 for this use case.

#### Option B — No DTMF needed (conversation-only flows)

- **Enable**: `G.722` (HD wideband, 16kHz)
- **Keep enabled**: `G.711U` as fallback

**CAVEAT**: Research on [livekit/sip #608](https://github.com/livekit/sip/issues/608)
shows that **switching G.711U-only vs G.722 made NO difference** for the
T-Mobile/VoLTE audio fading issue. Codec choice does not fix that bug.

### 3. HD Voice Enablement (Option B only)

Skip this for our use case — HD Voice uses G.722 which breaks DTMF.

If you split your fleet (IVR-heavy calls on one trunk, conversation-only
on another), enable HD Voice only on the conversation-only trunk:

Navigate to **Numbers** > [phone number] > **Voice** > **Services** > **Enable HD Voice**

### 4. Outbound Voice Profile

Navigate to **Voice API** > **Outbound Voice Profiles** > [profile]

- **Traffic Type**: `Conversational` (not `Short Duration`)
- **Service Plan**: enable France (`+33`) destinations
- **Max Channels**: set to your expected concurrency

### 5. Authentication

Navigate to **Real-Time Communications** > **Voice** > **SIP Trunking** >
[your trunk] > **Authentication & Routing** > **Outbound Calls Authentication**

- **Method**: `Credentials` (username + password)
- Record the username and password — you'll need them for the LiveKit outbound trunk

IP authentication is possible but subject to the cross-customer collision
risk described above. Credentials + `X-Telnyx-Username` header is the
only safe path.

### 6. SIP REFER (for warm transfers) — MANUAL ENABLEMENT REQUIRED

If you plan to use `transfer_sip_participant()` for warm transfers:

1. **Contact Telnyx support** to enable SIP REFER on your account — it is
   **not enabled by default**
2. Each REFER transfer has a **$0.10 surcharge** on top of per-minute call cost
3. Test via Telnyx API directly before wiring to LiveKit to validate

Source: [Telnyx SIP REFER release notes](https://telnyx.com/release-notes/transfer-calls-with-sip-refer-live),
LiveKit docs confirm: *"If using Telnyx as the SIP provider, SIP REFER must
be enabled for the account."*

## Required LiveKit Outbound Trunk Configuration

Create via `lk` CLI or LiveKit API. Example JSON for the DTMF-compatible
configuration:

```json
{
  "trunk": {
    "name": "telnyx-france-outbound",
    "address": "sip.telnyx.com",
    "numbers": ["+33XXXXXXXXX"],
    "auth_username": "YOUR_TELNYX_USERNAME",
    "auth_password": "YOUR_TELNYX_PASSWORD",
    "destination_country": "FR",
    "headers_to_attributes": {
      "X-Telnyx-Username": "YOUR_TELNYX_USERNAME"
    }
  }
}
```

Create via CLI:

```bash
lk sip outbound create telnyx-france-trunk.json
```

After creation, store the resulting LiveKit trunk ID in:

```env
LIVEKIT_SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxxx
```

Backward compatibility:

```env
TELNYX_SIP_TRUNK_ID=ST_xxxxxxxxxxxxx
```

That older variable name is misleading. In this repo it must contain the
**LiveKit** trunk ID, not the raw Telnyx portal SIP Connection ID.

### Critical parameters explained

- **`destination_country`: `"FR"`** — LiveKit region pinning. Calls originate
  from LiveKit's nearest POP to France, halving RTT vs default US routing.
  Source: <https://docs.livekit.io/telephony/features/region-pinning/>

- **`address`: `"sip.telnyx.com"`** — generic address that Telnyx routes via
  GeoDNS. Telnyx does not publish region-specific signaling endpoints.
  The regional routing happens via your Telnyx account anchorsite setting.

- **`headers_to_attributes`** with `X-Telnyx-Username`: **SECURITY-CRITICAL**
  (see Security Notice above). Also eliminates a 407 auth round-trip,
  saving 60-200ms of connection setup time.
  Source: <https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide>

## LiveKit Cloud Region

Deploy your LiveKit project to the **EU region** (not US default):

```toml
# livekit.toml
[project]
  subdomain = "optibot-315kjp2d"
  region = "eu"  # Frankfurt or Dublin
```

Without this, the agent process runs in US-East by default, adding ~150ms RTT
to every LLM inference call even if Telnyx is in Paris.

## Answering Machine Detection (AMD) — IMPORTANT LIMITATION

**Telnyx has native AMD with 97% accuracy**, but it lives in the Telnyx
Call Control / Voice API, NOT in the SIP signaling path.

**LiveKit's outbound SIP integration uses SIP INVITE on the trunk and
does not invoke Telnyx Call Control AMD.** So you cannot simply "enable
Telnyx AMD" and have it work with LiveKit.

Your two options:

### Option A — Keep our custom AMD (currently implemented)
Our `app/pipeline/amd.py` implements VAD-based heuristic AMD that runs
on the LiveKit audio stream. French tuning already applied:
- `human_speech_max_ms=2000` (French greeting length)
- `speech_threshold_ms=2400` (machine greeting min length)
- Combined with LLM-based `detected_answering_machine` tool using
  French trigger phrases

This works without needing Telnyx Call Control.

### Option B — Bridge via Telnyx Call Control
Originate calls via Telnyx Call Control API (not LiveKit SIP), use native
AMD, then bridge the answered call into a LiveKit room. This is the same
"bypass" architecture used to work around [livekit/sip #608](https://github.com/livekit/sip/issues/608).

**Tradeoff**: Option B requires significant code changes to `dispatch_outbound_call`
and breaks the unified LiveKit SIP path. Not recommended unless Option A's
accuracy is empirically insufficient.

**Note on French coverage**: Telnyx documentation does not explicitly state
language coverage for its AMD ML model. For French greetings, verify directly
with Telnyx support before relying on native AMD.

Source: [Telnyx AMD docs](https://developers.telnyx.com/docs/voice/programmable-voice/answering-machine-detection),
[Telnyx Premium AMD](https://telnyx.com/release-notes/premium-answering-machine-detection).

## Verification Checklist

After configuration, verify with an outbound test call to a French number:

- [ ] `lk sip outbound list` shows trunk with `destination_country: FR`
- [ ] `lk sip outbound list` shows `headers_to_attributes` includes `X-Telnyx-Username`
- [ ] Telnyx portal shows anchorsite = Frankfurt/Paris/Amsterdam/London
- [ ] Telnyx SIP Connection has the Outbound Voice Profile attached
- [ ] Telnyx SIP Connection outbound auth username/password are recorded
- [ ] Telnyx number is G.711 (NOT HD Voice / G.722) if DTMF is needed
- [ ] Telnyx portal shows SIP REFER enabled if you use warm transfers
- [ ] Repo `.env` contains `LIVEKIT_SIP_OUTBOUND_TRUNK_ID`
- [ ] Test call RTT feels natural (< 800ms turn-to-turn)
- [ ] Agent logs show `sip.callID` populated
- [ ] Agent process is in EU region (check `lk project list`)
- [ ] DTMF test: call an IVR, verify `press_digit()` reaches the mutuelle's menu
- [ ] Call ID headers visible in LiveKit participant attributes
  (see [livekit/sip PR #343](https://github.com/livekit/sip/pull/343))

## Known Issues (verified from GitHub as of April 2026)

### livekit/sip #642 — BYE routing loop on inbound Telnyx (OPEN, HIGH severity)
**Versions affected**: livekit-sip v1.2.0, Telnyx inbound UDP through
intermediate SIP proxies (TCP) to livekit-sip.

**Symptom**: When livekit-sip tears down an inbound call, the BYE includes
its own URI in the Route header set, causing the BYE to loop back through
the proxy chain to itself. livekit-sip responds 481 "Call does not exist"
to its own BYE. **Caller hears dead audio for ~49 seconds** until Telnyx's
RTP timeout fires its own BYE.

**Root cause**: livekit-sip is not stripping its own URI from the Route set
when building outbound in-dialog requests (RFC 3261 §12.2.1.1).

**Status**: OPEN, no fix merged.

**Mitigation**:
- Avoid intermediate SIP proxies between Telnyx and livekit-sip if possible
- Route directly via Telnyx FQDN instead of through your own SBC chain
- Watch for 49-second hangs in call teardown; alert on this pattern

Source: <https://github.com/livekit/sip/issues/642>

### livekit/sip #608 — Outbound audio artifacts on T-Mobile/VoLTE (OPEN)
**Symptom**: Words sound like they're fading in and out on T-Mobile or
VoLTE carriers. Telnyx recording is clean; receiving carrier delivers corrupt audio.

**Root cause**: LiveKit SIP bridge introduces discontinuities at audio chunk
boundaries during Opus->G.711/G.722 transcoding.

**Workarounds that DID NOT work** (per reporter):
- -6 dB / -9 dB gain reduction
- 3.5 kHz low-pass filter
- Soft limiter
- Dithering
- Changing TTS sample rate
- Switching to G.711U only
- Removing G.722
- Enabling Krisp

**Only confirmed clean path**: Bypass LiveKit's SIP bridge entirely and
originate via Telnyx Call Control API, then bridge media into LiveKit.

**Our partial mitigation**:
- Set `audio_sample_rate=24000` on `RoomOutputOptions` (done in commit 39a844c)
- Monitor for user-reported audio quality issues
- If it becomes a blocker, implement Option B (Call Control bridging) above

Source: <https://github.com/livekit/sip/issues/608>

### livekit/sip #49 — Unhandled SIP response log noise (OPEN since Jan 2024)
**Symptom**: "UnhandledResponseHandler handler not added" warnings in logs
when Telnyx sends multiple 200 OK responses to the initial INVITE.

**Impact**: Cosmetic only — calls still work. Log noise on high-concurrency
deployments can obscure real errors.

**Mitigation**: Filter this specific warning from production log aggregation.

Source: <https://github.com/livekit/sip/issues/49>

### LiveKit #3841 — Silent worker death (OPEN)
**Symptom**: Agent process dies silently with `DuplexClosed` error after
several calls. Most common with Deepgram STT + Cartesia TTS combination.

**Mitigation**:
- Keep worker heartbeat thread enabled (`_start_worker_heartbeat_thread` in main.py)
- Alert on `DuplexClosed` in production logs
- Redeploy on worker crash (Kubernetes restartPolicy: Always)

Source: <https://github.com/livekit/agents/issues/3841>

### LiveKit #4053 — EU latency increase (OPEN)
**Symptom**: Agent in LiveKit Cloud EU has ~2s extra per-turn latency vs local.

**Root cause**: Unknown; reported but not diagnosed.

**Mitigation**:
- `destination_country="FR"` on outbound trunk
- Telnyx anchorsite = Paris or Frankfurt
- Prompt caching on LLM provider (OpenAI/Anthropic both support)
- Keep system prompt under 1000 tokens
- Deploy agent to LiveKit Cloud EU region (not US-East default)

Source: <https://github.com/livekit/agents/issues/4053>

## Production-Confirmed Workarounds Summary

| Problem | Workaround | Source |
|---|---|---|
| Cross-customer SIP IP collision | `X-Telnyx-Username` header | Telnyx LiveKit guide |
| T-Mobile/VoLTE audio artifacts | Bypass LiveKit SIP bridge via Call Control API | livekit/sip #608 |
| BYE routing loop 49s hang | Avoid intermediate SIP proxies | livekit/sip #642 |
| G.722 breaks DTMF for IVR | Use G.711 + RFC 2833 telephone-event | Telnyx docs |
| EU latency | region="eu" + destination_country="FR" + anchorsite EU | LiveKit #4053 |
| SIP REFER transfers | Enable via Telnyx support + expect $0.10 surcharge | Telnyx release notes |
| Native AMD not in SIP path | Use in-agent VAD-based AMD (current approach) | Telnyx AMD docs |

## Sources

- Telnyx + LiveKit configuration guide: <https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide>
- LiveKit Telnyx provider docs: <https://docs.livekit.io/telephony/start/providers/telnyx/>
- LiveKit SIP outbound trunk: <https://docs.livekit.io/sip/trunk-outbound/>
- LiveKit region pinning: <https://docs.livekit.io/telephony/features/region-pinning/>
- Telnyx audio and codecs (G.722 DTMF warning): <https://support.telnyx.com/en/articles/3192298-audio-and-codecs>
- Telnyx EU Voice AI infrastructure: <https://telnyx.com/release-notes/europe-voice-ai-infra>
- Telnyx Paris GPU PoP announcement: <https://telnyx.com/release-notes/europe-voice-ai-infra>
- Telnyx AMD (Premium): <https://telnyx.com/release-notes/premium-answering-machine-detection>
- Telnyx AMD developer docs: <https://developers.telnyx.com/docs/voice/programmable-voice/answering-machine-detection>
- Telnyx SIP REFER: <https://telnyx.com/release-notes/transfer-calls-with-sip-refer-live>
- livekit/sip #642 (BYE routing loop): <https://github.com/livekit/sip/issues/642>
- livekit/sip #608 (audio fading): <https://github.com/livekit/sip/issues/608>
- livekit/sip #49 (unhandled response log noise): <https://github.com/livekit/sip/issues/49>
- livekit/sip PR #343 (Telnyx call ID headers): <https://github.com/livekit/sip/pull/343>
- LiveKit agents #3841 (silent worker death): <https://github.com/livekit/agents/issues/3841>
- LiveKit agents #4053 (EU latency): <https://github.com/livekit/agents/issues/4053>
- LiveKit agents #4026 (SIP outbound quality): <https://github.com/livekit/agents/issues/4026>

# Telnyx + LiveKit Configuration Runbook (France / EU)

All research in this document is sourced from official Telnyx and LiveKit
documentation current as of April 2026. Every recommendation is a portal
or API configuration change — no code changes are needed.

## Why This Matters

Research confirmed three facts that make Telnyx configuration critical for
French telephony:

1. **Telnyx Paris GPU PoP exists** with sub-200ms round-trip time for Voice AI
   Source: <https://telnyx.com/release-notes/europe-voice-ai-infra>
2. **`sip.telnyx.com` is the US proxy** — using it from Europe adds ~120ms
3. **LiveKit region pinning via `destination_country="FR"`** keeps calls in-region
   Source: <https://docs.livekit.io/telephony/features/region-pinning/>

LiveKit #4053 (open) reports EU-hosted LiveKit Cloud adds ~2s per turn vs local.
Combined with a US-routed SIP trunk, this compounds to unusable latency.

## Required Telnyx Portal Configuration

### 1. Anchorsite (Voice API region)

Navigate to **Voice API** > **Applications** > [your app] > **Anchorsite**

Set anchorsite to **one of**:
- `Frankfurt, Germany` (primary EU datacenter — recommended default)
- `Paris, France` (GPU PoP — preferred for French Voice AI)
- `Amsterdam, Netherlands`
- `London, UK`

Do **NOT** leave at default (`Latency` or US sites). The default chooses the
closest POP to the caller, which for agent-driven outbound is random.

### 2. SIP Trunk Codec Configuration

Navigate to **Real-Time Communications** > **Voice** > **SIP Trunking** >
[your trunk] > **Inbound** tab > **Codecs**

- **Enable**: `G.722` (HD wideband, 16kHz — preferred for voice AI)
- **Keep enabled**: `G.711U` (PCMU, 8kHz fallback for legacy carriers)
- **Disable**: `G.729` (compressed, degrades voice quality)

Research source: LiveKit SIP #608 identified that audio artifacts are caused
by Opus->G.711 transcoding in the LiveKit SIP bridge. G.722 (wideband) reduces
these artifacts significantly.

### 3. HD Voice Enablement

Navigate to **Numbers** > [phone number] > **Voice** > **Services** > **Enable HD Voice**

Enable on every outbound caller ID number. Telnyx is the only LiveKit SIP
provider with HD Voice support.

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

IP authentication is possible but harder to maintain; credentials are recommended.

## Required LiveKit Outbound Trunk Configuration

Create via `lk` CLI or LiveKit API. Example JSON:

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

### Critical parameters explained

- **`destination_country`: `"FR"`** — LiveKit region pinning. Calls originate
  from LiveKit's nearest POP to France, halving RTT vs default US routing.
  Source: <https://docs.livekit.io/telephony/features/region-pinning/>

- **`address`: `"sip.telnyx.com"`** — generic address; Telnyx routes based on
  geolocation automatically. Telnyx does NOT publish regional SIP endpoints
  (unlike Amazon SIP, for example); they use GeoDNS.

- **`headers_to_attributes`** with `X-Telnyx-Username`: LiveKit sends the first
  INVITE without a username; Telnyx responds with 407 Proxy Authentication
  Required, forcing a re-INVITE. Including the username in a custom header
  eliminates this round-trip and reduces connection setup by 60-200ms.
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

## Verification Checklist

After configuration, verify with an outbound test call to a French number:

- [ ] `lk sip outbound list` shows trunk with `destination_country: FR`
- [ ] Telnyx portal shows anchorsite = Frankfurt/Paris/Amsterdam
- [ ] Telnyx number has HD Voice = enabled
- [ ] Telnyx trunk codec list shows G.722 + G.711U (no G.729)
- [ ] Test call RTT < 200ms audible (subjective "natural" feel)
- [ ] Agent logs show `sip.callID` populated
- [ ] Agent process is in EU region (check `lk project list`)

## Known Issues (as of April 2026)

### LiveKit #4026 — Outbound SIP audio fading (OPEN)
**Symptom**: Words sound like they're fading in and out, especially on T-Mobile
or VoLTE carriers.

**Root cause**: Opus->G.711 transcoding discontinuities in LiveKit SIP bridge.
Server-side bug, no client fix available.

**Mitigation**:
- Enable G.722 codec (reduces Opus->codec boundary artifacts)
- Set `audio_sample_rate=24000` on `RoomOutputOptions` (already done in our code)
- Monitor `participant_attributes_changed` events for codec negotiation

### LiveKit #3841 — Silent worker death (OPEN)
**Symptom**: Agent process dies silently with `DuplexClosed` error after
several calls. Most common with Deepgram STT + Cartesia TTS combination.

**Mitigation**:
- Keep worker heartbeat thread enabled (`_start_worker_heartbeat_thread` in main.py)
- Alert on `DuplexClosed` in production logs
- Redeploy on worker crash (Kubernetes restartPolicy: Always)

### LiveKit #4053 — EU latency increase (OPEN)
**Symptom**: Agent in LiveKit Cloud EU has ~2s extra per-turn latency.

**Mitigation**:
- `destination_country="FR"` on outbound trunk
- Telnyx anchorsite = Paris or Frankfurt
- Prompt caching on LLM provider (OpenAI/Anthropic both support)
- Keep system prompt under 1000 tokens

## Sources

- Telnyx + LiveKit configuration guide: <https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide>
- LiveKit Telnyx provider docs: <https://docs.livekit.io/telephony/start/providers/telnyx/>
- LiveKit SIP outbound trunk: <https://docs.livekit.io/sip/trunk-outbound/>
- LiveKit region pinning: <https://docs.livekit.io/telephony/features/region-pinning/>
- Telnyx EU Voice AI infrastructure: <https://telnyx.com/release-notes/europe-voice-ai-infra>
- Telnyx Paris GPU PoP announcement: <https://telnyx.com/resources/europe-voice-ai-infra>
- LiveKit SIP issue #4026 (audio fading): <https://github.com/livekit/agents/issues/4026>
- LiveKit SIP issue #608 (transcoding artifacts): <https://github.com/livekit/sip/issues/608>
- LiveKit issue #3841 (silent worker death): <https://github.com/livekit/agents/issues/3841>
- LiveKit issue #4053 (EU latency): <https://github.com/livekit/agents/issues/4053>

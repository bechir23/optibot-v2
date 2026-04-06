"""Generate Microsoft vs OptiBot v2 comparison + pricing + source mapping."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

fig, axes = plt.subplots(2, 2, figsize=(30, 22))
fig.patch.set_facecolor('#FAFAFA')
fig.suptitle('OptiBot v2 — Complete Architecture Analysis', fontsize=20, fontweight='bold', y=0.98, color='#1565C0')

# ══════════════════════════════════════════════════════════
# TOP-LEFT: Microsoft C4 → OptiBot v2 Mapping
# ══════════════════════════════════════════════════════════
ax1 = axes[0][0]
ax1.set_xlim(0, 14)
ax1.set_ylim(0, 11)
ax1.axis('off')
ax1.set_title('Microsoft call-center-ai → OptiBot v2 Mapping', fontsize=13, fontweight='bold', pad=15)

def box1(ax, x, y, w, h, text, color, fontsize=8):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                          facecolor=color, edgecolor='#37474F', linewidth=1.2)
    ax.add_patch(rect)
    ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fontsize,
            fontweight='bold', color='#212121', wrap=True)

rows = [
    ('Microsoft Component', 'OptiBot v2 Equivalent', 'Cost / Status'),
    ('Azure Communication\nServices (PSTN)', 'LiveKit SIP +\nTelnyx/Twilio', 'Telnyx: $0.004/min\nTwilio: $0.013/min'),
    ('Azure Cognitive\nServices (STT)', 'Deepgram Nova-3\n+ Keyterm Prompting', '$0.0092/min\n90% keyword recall'),
    ('Azure Cognitive\nServices (TTS)', 'Cartesia Sonic-3\nFrench voice', '$0.006/1K chars\n40ms first audio'),
    ('GPT-4.1 + GPT-4.1-nano\n(dual LLM)', 'Mistral + Groq 8B\n(dual LLM)', 'Mistral: ~$0.002/1K tok\nGroq: FREE'),
    ('Azure AI Search\n(BM25 + vector)', 'Supabase pgvector\n+ query expansion', 'FREE tier\n(Supabase)'),
    ('Cosmos DB\n(conversations)', 'Supabase PostgreSQL\n+ RLS tenants', 'FREE tier'),
    ('Redis (cache)', 'Redis (self-hosted)\n3-tier L1/L2/L3', 'FREE (Docker)'),
    ('Azure App Config\n(feature flags)', 'Redis-backed\nfeature flags', 'FREE (Docker)'),
    ('Azure Monitor\n(OpenTelemetry)', 'Jaeger + Prometheus\n+ Grafana', 'FREE (Docker)'),
    ('Azure Event Grid\n(broker/queues)', 'Redis Pub/Sub\n+ Streams', 'FREE (Docker)'),
]

colors_left = ['#90CAF9'] + ['#BBDEFB'] * 10
colors_mid = ['#90CAF9'] + ['#C8E6C9'] * 10
colors_right = ['#90CAF9'] + ['#FFF9C4'] * 10

for i, (left, mid, right) in enumerate(rows):
    y = 10 - i * 0.95
    box1(ax1, 0.1, y, 4.2, 0.8, left, colors_left[i])
    ax1.text(4.5, y+0.4, '→', ha='center', va='center', fontsize=16, fontweight='bold', color='#E65100')
    box1(ax1, 4.8, y, 4.2, 0.8, mid, colors_mid[i])
    box1(ax1, 9.3, y, 4.5, 0.8, right, colors_right[i])

# ══════════════════════════════════════════════════════════
# TOP-RIGHT: What we clone / keep / build new
# ══════════════════════════════════════════════════════════
ax2 = axes[0][1]
ax2.set_xlim(0, 14)
ax2.set_ylim(0, 11)
ax2.axis('off')
ax2.set_title('Source of Every Component (Clone / Keep / New)', fontsize=13, fontweight='bold', pad=15)

sources = [
    ('Component', 'Source', 'Action', '#78909C'),
    # From Microsoft (clone pattern)
    ('LLM tool-calling\n(no hardcoded intents)', 'Microsoft\ncall-center-ai', 'CLONE PATTERN\nadapt for Mistral', '#BBDEFB'),
    ('json-repair on\nevery LLM response', 'Microsoft\ncall-center-ai', 'CLONE DIRECTLY\npip install json-repair', '#BBDEFB'),
    ('tiktoken context\nwindow management', 'Microsoft\ncall-center-ai', 'CLONE PATTERN\ntruncate at 6K tokens', '#BBDEFB'),
    ('CallState dynamic\nmodel (not FSM)', 'Microsoft\ncall-center-ai', 'CLONE + ADAPT\nadd dossier fields', '#BBDEFB'),
    ('OpenTelemetry dual\nlayer monitoring', 'Microsoft\ncall-center-ai', 'CLONE PATTERN\nreplace Azure Monitor', '#BBDEFB'),
    ('Soft/Hard timeout\n(4s/15s)', 'Microsoft\ncall-center-ai', 'CLONE DIRECTLY\nsame logic', '#BBDEFB'),
    # From OptiBot (keep)
    ('STT Correction\n(French mutuelles)', 'OptiBot v1\ntools/', 'KEEP + FIX\nremove Pipecat dep', '#C8E6C9'),
    ('Hold Detector\n(2-tier)', 'OptiBot v1\ntools/', 'KEEP + FIX\nlen >= 3 bug', '#C8E6C9'),
    ('Naturalizer\n(Fr variations)', 'OptiBot v1\nactions/', 'KEEP + FIX\nbackchannel leak', '#C8E6C9'),
    ('41 Action defs\n(seed data)', 'OptiBot v1\nactions/', 'CONVERT\nPython → SQL seed', '#C8E6C9'),
    # New (LiveKit)
    ('SIP outbound +\nDTMF + IVR', 'LiveKit Agents\n(new framework)', 'BUILD NEW\nLiveKit IVR recipe', '#FFE0B2'),
    ('Barge-in +\nturn detection', 'LiveKit Agents\n+ Shuo pattern', 'BUILD NEW\nbuilt-in to LiveKit', '#FFE0B2'),
]

for i, (comp, source, action, color) in enumerate(sources):
    y = 10.2 - i * 0.78
    fs = 7 if i > 0 else 8
    box1(ax2, 0.1, y, 4.5, 0.65, comp, color, fontsize=fs)
    box1(ax2, 4.8, y, 3.5, 0.65, source, color, fontsize=fs)
    box1(ax2, 8.5, y, 5.3, 0.65, action, color, fontsize=fs)

# ══════════════════════════════════════════════════════════
# BOTTOM-LEFT: Full pricing breakdown
# ══════════════════════════════════════════════════════════
ax3 = axes[1][0]
ax3.set_xlim(0, 14)
ax3.set_ylim(0, 11)
ax3.axis('off')
ax3.set_title('Complete Pricing — Per Call + Monthly Infrastructure', fontsize=13, fontweight='bold', pad=15)

pricing = [
    ('Service', 'Per 5-min Call', 'Monthly (300 calls/day)', 'Free Tier?', '#78909C'),
    ('Deepgram Nova-3 (STT)', '$0.046', '$414', 'Pay-as-you-go', '#FBE9E7'),
    ('Cartesia Sonic-3 (TTS)', '~$0.03', '~$270', 'Pay-as-you-go', '#FBE9E7'),
    ('Mistral (LLM)', '~$0.01', '~$90', 'Pay-as-you-go', '#FBE9E7'),
    ('Groq (IVR/classifier)', '$0.00', '$0', 'YES - 14K req/day', '#E8F5E9'),
    ('Telnyx SIP (PSTN)', '$0.02', '$180', 'Pay-as-you-go', '#FBE9E7'),
    ('mistral-embed (RAG)', '~$0.001', '~$9', 'Pay-as-you-go', '#FBE9E7'),
    ('Supabase (DB+pgvector)', '$0.00', '$0', 'YES - 500MB', '#E8F5E9'),
    ('LiveKit (self-hosted)', '$0.00', '$0', 'YES - open source', '#E8F5E9'),
    ('Redis (Docker)', '$0.00', '$0', 'YES - self-hosted', '#E8F5E9'),
    ('Jaeger+Prometheus+Grafana', '$0.00', '$0', 'YES - self-hosted', '#E8F5E9'),
    ('Scaleway hosting', '—', '$60-110', 'No (but cheapest EU)', '#FFF9C4'),
    ('TOTAL', '~$0.11', '~$1,023-1,073/mo', '', '#90CAF9'),
]

for i, (svc, per_call, monthly, free, color) in enumerate(pricing):
    y = 10.2 - i * 0.78
    fs = 7 if i > 0 else 8
    w = 'bold' if i == 0 or i == len(pricing)-1 else 'normal'
    box1(ax3, 0.1, y, 4.5, 0.65, svc, color, fontsize=fs)
    box1(ax3, 4.8, y, 2.3, 0.65, per_call, color, fontsize=fs)
    box1(ax3, 7.3, y, 3.2, 0.65, monthly, color, fontsize=fs)
    box1(ax3, 10.7, y, 3.1, 0.65, free, color, fontsize=fs)

# ══════════════════════════════════════════════════════════
# BOTTOM-RIGHT: What's REMOVED from OptiBot v1 + Testing
# ══════════════════════════════════════════════════════════
ax4 = axes[1][1]
ax4.set_xlim(0, 14)
ax4.set_ylim(0, 11)
ax4.axis('off')
ax4.set_title('OptiBot v1 Files: REMOVED vs KEPT + Testing Plan', fontsize=13, fontweight='bold', pad=15)

# Removed files
removed = [
    ('REMOVED (why)', 'Replaced By'),
    ('pipeline/builder.py\n(500+ lines Pipecat)', 'LiveKit Agent pattern\n(outbound_caller.py)'),
    ('actions/processor.py\n(6 keyword lists)', 'LLM tool-calling\n(no intents needed)'),
    ('state/call_state.py\n(rigid FSM)', 'Dynamic CallState\n(Microsoft model)'),
    ('actions/selector.py\n(separate LLM call)', 'LLM selects tools\ndirectly in agent'),
    ('actions/llm_json.py\n(no json-repair)', 'services/llm.py\n(+json-repair +tiktoken)'),
    ('webhooks/server.py\n(race conditions)', 'app/main.py\n(FastAPI + LiveKit)'),
    ('services/transport.py\n(Daily.co)', 'LiveKit SIP trunk'),
    ('services/outbound.py\n(race condition+no timeout)', 'LiveKit outbound\n(built-in retry)'),
]

for i, (left, right) in enumerate(removed):
    y = 10.2 - i * 0.75
    color_l = '#78909C' if i == 0 else '#FFCDD2'
    color_r = '#78909C' if i == 0 else '#C8E6C9'
    box1(ax4, 0.1, y, 5.5, 0.6, left, color_l, fontsize=7)
    ax4.text(5.8, y+0.3, '→', ha='center', va='center', fontsize=14, color='#2E7D32')
    box1(ax4, 6.1, y, 5.5, 0.6, right, color_r, fontsize=7)

# Testing section
y_test = 10.2 - len(removed) * 0.75 - 0.3
ax4.text(0.3, y_test, 'TESTING — How to test without real PSTN:', fontsize=9, fontweight='bold', color='#1565C0')
tests = [
    'Twilio test numbers: +15005550006 (always answers), +15005550001 (busy)',
    'Telnyx test mode: free SIP calls to test endpoints (no PSTN charges)',
    'LiveKit local: docker compose up → agent connects to local LiveKit server',
    'IVR test: Twilio TwiML IVR simulator (build test menu, bot navigates it)',
    'Audio roundtrip: Cartesia TTS → WAV → Deepgram STT → verify French accuracy',
    'Load test: 5/10/25 concurrent mock calls via pytest-asyncio',
]
for j, t in enumerate(tests):
    ax4.text(0.5, y_test - 0.35 - j*0.32, f"  {j+1}. {t}", fontsize=7.5, color='#37474F')

plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig('C:/Users/bechi/optibot-v2/docs/architecture_comparison.png', dpi=150, bbox_inches='tight',
            facecolor='#FAFAFA', edgecolor='none')
print("Saved: C:/Users/bechi/optibot-v2/docs/architecture_comparison.png")

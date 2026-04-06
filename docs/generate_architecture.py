"""Generate OptiBot v2 architecture diagram as PNG."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(1, 1, figsize=(28, 20))
ax.set_xlim(0, 28)
ax.set_ylim(0, 20)
ax.axis('off')
fig.patch.set_facecolor('#FAFAFA')

# ── Color scheme ──
C_DOCKER = '#E3F2FD'       # light blue - docker services
C_LIVEKIT = '#E8F5E9'      # light green - LiveKit
C_LLM = '#FFF3E0'          # light orange - LLM/AI
C_DATA = '#F3E5F5'         # light purple - data layer
C_EXTERNAL = '#FBE9E7'     # light red - external paid APIs
C_KEPT = '#C8E6C9'         # green - kept from OptiBot
C_MICROSOFT = '#BBDEFB'    # blue - from Microsoft
C_NEW = '#FFE0B2'          # orange - new/LiveKit
C_BORDER = '#37474F'
C_ARROW = '#546E7A'

def box(x, y, w, h, label, sublabel='', color='white', fontsize=9, bold=True):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                          facecolor=color, edgecolor=C_BORDER, linewidth=1.5)
    ax.add_patch(rect)
    weight = 'bold' if bold else 'normal'
    ax.text(x + w/2, y + h/2 + (0.12 if sublabel else 0), label,
            ha='center', va='center', fontsize=fontsize, fontweight=weight, color='#212121')
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.2, sublabel,
                ha='center', va='center', fontsize=7, color='#616161', style='italic')

def arrow(x1, y1, x2, y2, label='', color=C_ARROW, style='->', lw=1.5):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=lw, connectionstyle='arc3,rad=0.05'))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my + 0.15, label, ha='center', va='center', fontsize=7, color='#455A64',
                bbox=dict(boxstyle='round,pad=0.1', facecolor='white', edgecolor='none', alpha=0.8))

def section_box(x, y, w, h, label, color):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                          facecolor=color, edgecolor=C_BORDER, linewidth=2, alpha=0.3)
    ax.add_patch(rect)
    ax.text(x + 0.3, y + h - 0.3, label, fontsize=11, fontweight='bold', color='#37474F')

# ══════════════════════════════════════════════════════════
# TITLE
# ══════════════════════════════════════════════════════════
ax.text(14, 19.5, 'OptiBot v2 — Production Architecture', ha='center', fontsize=18, fontweight='bold', color='#1565C0')
ax.text(14, 19.1, 'LiveKit Agents + Microsoft call-center-ai patterns + French voice optimization',
        ha='center', fontsize=10, color='#616161')

# ══════════════════════════════════════════════════════════
# DOCKER COMPOSE BOUNDARY
# ══════════════════════════════════════════════════════════
section_box(0.3, 3.5, 27.4, 15, 'Docker Compose Stack (self-hosted)', C_DOCKER)

# ══════════════════════════════════════════════════════════
# LIVEKIT SERVER (center-left)
# ══════════════════════════════════════════════════════════
section_box(0.8, 10, 7.5, 7.5, 'LiveKit Server :7880 (NEW — replaces Daily.co)', C_LIVEKIT)

box(1.2, 15.8, 3.2, 0.9, 'IVR Navigator', 'Groq 8B, DTMF, 30ms', C_NEW)
box(4.8, 15.8, 3.1, 0.9, 'Voicemail Detector', 'Groq 8B dedicated', C_NEW)

box(1.2, 14.5, 6.7, 0.9, 'Outbound Caller Agent', 'Mistral LLM + Tool-Calling (Microsoft pattern)', C_MICROSOFT)

box(1.2, 13.2, 3.2, 0.9, 'SIP Trunk', 'Telnyx/Twilio PSTN', C_NEW)
box(4.8, 13.2, 3.1, 0.9, 'WebRTC Room', 'Audio streaming', C_NEW)

box(1.2, 11.8, 2.1, 0.9, 'Turn Detection', 'Built-in VAD', C_NEW)
box(3.6, 11.8, 2.1, 0.9, 'Barge-In', 'Cancel buffer', C_NEW)
box(6.0, 11.8, 2.1, 0.9, 'DTMF Gen', 'Tone sending', C_NEW)

box(1.2, 10.5, 6.7, 0.9, 'Echo Cancellation (AEC)', 'Microsoft pattern: RMS VAD + reference signal', C_MICROSOFT)

# Arrows within LiveKit
arrow(2.8, 15.8, 2.8, 15.4)  # IVR → Agent
arrow(6.3, 15.8, 4.5, 15.4)  # Voicemail → Agent
arrow(2.8, 14.5, 2.8, 14.1)  # Agent → SIP
arrow(6.3, 14.5, 6.3, 14.1)  # Agent → WebRTC

# ══════════════════════════════════════════════════════════
# APP CORE (center)
# ══════════════════════════════════════════════════════════
section_box(8.8, 10, 9.5, 7.5, 'OptiBot App :8080 (FastAPI + Agents)', '#FFF8E1')

# Tools row (LLM-callable, NOT hardcoded intents)
box(9.2, 16, 2.5, 0.7, 'give_patient_info', 'LLM tool', C_MICROSOFT, fontsize=8)
box(11.9, 16, 2.5, 0.7, 'ask_status', 'LLM tool', C_MICROSOFT, fontsize=8)
box(14.6, 16, 3.3, 0.7, 'extract_data', 'json-repair + tiktoken', C_MICROSOFT, fontsize=8)
ax.text(13.5, 16.95, 'LLM-Callable Tools (NO hardcoded intents — Microsoft pattern)',
        ha='center', fontsize=8, fontweight='bold', color='#E65100')

# Pipeline (kept from OptiBot)
box(9.2, 14.9, 2.8, 0.8, 'STT Correction', 'French mutuelles', C_KEPT)
box(12.3, 14.9, 2.8, 0.8, 'Hold Detector', '2-tier (bug-fixed)', C_KEPT)
box(15.4, 14.9, 2.5, 0.8, 'Naturalizer', 'Fr variations', C_KEPT)

# Services
box(9.2, 13.6, 2.8, 0.8, 'LLM Service', 'Dual: Mistral+Groq', C_MICROSOFT)
box(12.3, 13.6, 2.8, 0.8, 'RAG Service', 'Query expansion', C_MICROSOFT)
box(15.4, 13.6, 2.5, 0.8, 'Cache Service', '3-tier L1/L2/L3', C_MICROSOFT)

# Models
box(9.2, 12.3, 4.2, 0.8, 'CallState (dynamic model)', 'NOT FSM — Microsoft pattern', C_MICROSOFT)
box(13.7, 12.3, 4.2, 0.8, 'Feature Flags', 'Redis-backed, runtime toggle', C_MICROSOFT)

# API
box(9.2, 11, 2.8, 0.8, '/api/call', 'POST outbound', '#FFF8E1')
box(12.3, 11, 2.8, 0.8, '/api/schedule', 'Batch calls', '#FFF8E1')
box(15.4, 11, 2.5, 0.8, '/metrics', 'Prometheus', '#FFF8E1')

# Observability
box(9.2, 10.2, 8.7, 0.5, 'OpenTelemetry: spans (call.stt, call.llm, call.tts, call.ivr) + structlog PII scrub',
    '', C_MICROSOFT, fontsize=7.5, bold=False)

# ══════════════════════════════════════════════════════════
# INFRASTRUCTURE SERVICES (right)
# ══════════════════════════════════════════════════════════
section_box(18.8, 10, 8.5, 7.5, 'Infrastructure (all FREE, self-hosted)', C_DATA)

box(19.2, 16, 3.8, 0.9, 'Redis :6379', 'Cache L2 + Pub/Sub + Features', C_DATA)
box(23.3, 16, 3.6, 0.9, 'Supabase PostgreSQL', 'pgvector + RLS tenants', C_DATA)

box(19.2, 14.7, 3.8, 0.9, 'Jaeger :16686', 'Distributed tracing (OTEL)', C_DATA)
box(23.3, 14.7, 3.6, 0.9, 'Prometheus :9090', 'Metrics scraping', C_DATA)

box(19.2, 13.4, 7.7, 0.9, 'Grafana :3001 — Dashboard: latency, IVR success, cache hits, errors', '', C_DATA)

box(19.2, 12.1, 3.8, 0.9, 'Nginx', 'TLS + reverse proxy', C_DATA)
box(23.3, 12.1, 3.6, 0.9, 'Cloudflare', 'DDoS + WAF (free)', C_DATA)

box(19.2, 10.8, 7.7, 0.8, 'Security: Fernet encryption, JWT auth, CORS allowlist, PII scrub, audit log',
    '', '#FFCDD2', fontsize=8, bold=False)

# ══════════════════════════════════════════════════════════
# EXTERNAL SERVICES (bottom)
# ══════════════════════════════════════════════════════════
section_box(0.8, 3.8, 26.5, 5.5, 'External APIs (some paid, some free)', C_EXTERNAL)

# STT / TTS / LLM
box(1.2, 7.6, 3.5, 1, 'Deepgram Nova-3', 'STT + Keyterm Prompting\n$0.0092/min', C_EXTERNAL)
box(5.0, 7.6, 3.5, 1, 'Cartesia Sonic-3', 'TTS French, 40ms TTFA\n$0.006/1K chars', C_EXTERNAL)
box(8.8, 7.6, 3.5, 1, 'Mistral AI', 'LLM (conversation)\n~$0.002/1K tokens', C_EXTERNAL)
box(12.6, 7.6, 3.5, 1, 'Groq', 'LLM (IVR/classifier)\nFREE 14K req/day', C_EXTERNAL)

# Telephony
box(16.4, 7.6, 3.5, 1, 'Telnyx SIP', 'French PSTN trunk\n$0.004/min', C_EXTERNAL)
box(20.2, 7.6, 3.5, 1, 'Twilio (backup)', 'PSTN + phone number\n$0.013/min', C_EXTERNAL)
box(24.0, 7.6, 3.0, 1, 'mistral-embed', 'RAG embeddings\n~$0.001/1K tokens', C_EXTERNAL)

# Actors
box(1.2, 4.5, 4, 1.2, 'MUTUELLE', 'Called party\n(Harmonie, MGEN, AG2R...)', '#FFCDD2', fontsize=10)
box(6, 4.5, 4, 1.2, 'OPTICIAN', 'Dashboard user\n(tenant = 1 optician)', '#C8E6C9', fontsize=10)
box(11, 4.5, 4, 1.2, 'ADMIN', 'OptiBot team\nGrafana + Jaeger', '#BBDEFB', fontsize=10)

# Testing
box(16, 4.5, 5.5, 1.2, 'TEST MODE', 'Twilio test numbers\nNo real PSTN needed\n+15005550006', '#FFF9C4', fontsize=9)
box(22, 4.5, 5, 1.2, 'SCALEWAY PARIS', 'Production deploy\n$60-110/month\nL4 GPU optional', '#E0E0E0', fontsize=9)

# ══════════════════════════════════════════════════════════
# KEY ARROWS (connections between sections)
# ══════════════════════════════════════════════════════════
# LiveKit ↔ App
arrow(8.3, 15, 9.2, 15, 'audio frames', lw=2)
arrow(8.3, 14, 9.2, 14, 'tool calls', lw=2)
arrow(8.3, 13, 9.2, 13, 'state sync', lw=1.5)

# App ↔ Infrastructure
arrow(17.9, 16.3, 19.2, 16.3, 'cache ops', lw=1.5)
arrow(17.9, 15.1, 19.2, 15.1, 'traces', lw=1.5)
arrow(17.9, 13.7, 23.3, 16.5, 'pgvector\nRAG', lw=1.5)
arrow(17.9, 11.3, 19.2, 11.3, '', lw=1.5)

# External connections
arrow(3.0, 8.6, 3.0, 10, 'STT stream', lw=1.5)
arrow(6.7, 8.6, 6.7, 10, 'TTS stream', lw=1.5)
arrow(10.5, 8.6, 10.5, 10, 'completions', lw=1.5)
arrow(14.3, 8.6, 14.3, 10, 'IVR decisions', lw=1.5)
arrow(18.1, 8.6, 3.5, 10, 'SIP trunk', lw=2)

# Mutuelle connection
arrow(3.2, 5.7, 2.8, 7.6, 'PSTN call', lw=2, color='#D32F2F')

# ══════════════════════════════════════════════════════════
# LEGEND
# ══════════════════════════════════════════════════════════
legend_x, legend_y = 0.5, 0.5
ax.text(legend_x, legend_y + 2.5, 'LEGEND — Source of each component:', fontsize=10, fontweight='bold', color='#37474F')

for i, (color, label) in enumerate([
    (C_MICROSOFT, 'From Microsoft call-center-ai (tool-calling, json-repair, tiktoken, OTEL, CallState, AEC, RAG)'),
    (C_KEPT, 'Kept from OptiBot v1 (STT correction, hold detector, naturalizer, 41 action seeds)'),
    (C_NEW, 'New — LiveKit Agents (SIP outbound, DTMF, IVR nav, WebRTC rooms, turn detection, barge-in)'),
    (C_DATA, 'Self-hosted infrastructure (Redis, Jaeger, Prometheus, Grafana — all FREE)'),
    (C_EXTERNAL, 'External APIs (Deepgram, Cartesia, Mistral, Groq, Telnyx — see pricing)'),
]):
    rect = FancyBboxPatch((legend_x, legend_y + 2 - i*0.45), 0.4, 0.3,
                          boxstyle="round,pad=0.05", facecolor=color, edgecolor=C_BORDER, linewidth=1)
    ax.add_patch(rect)
    ax.text(legend_x + 0.6, legend_y + 2.15 - i*0.45, label, fontsize=8, color='#37474F', va='center')

plt.tight_layout()
plt.savefig('C:/Users/bechi/optibot-v2/docs/architecture.png', dpi=150, bbox_inches='tight',
            facecolor='#FAFAFA', edgecolor='none')
print("Saved: C:/Users/bechi/optibot-v2/docs/architecture.png")

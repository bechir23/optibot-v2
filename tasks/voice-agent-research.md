# Production Voice Agent Research: VAPI, Retell AI, Bland AI, and Best Practices

**Date:** 2026-04-06  
**Purpose:** Extract concrete patterns for OptiBot v2 (French optician voice AI)

---

## 1. VAPI.ai — Deep Dive

### Architecture: Orchestration Layer
VAPI is a **real-time orchestration layer** sitting atop three swappable components: STT, LLM, TTS. It does NOT modify user prompts ("treats user prompts as sacred"). Key proprietary models run between the components:

- **Endpointing**: Custom fusion audio-text model (not silence-based VAD) that examines both vocal tone and semantic content to determine when user finished speaking
- **Backchannel Detection**: Proprietary fusion model identifies when "yeah", "uh-huh" are fillers vs. actual turn signals
- **Interruption Detection**: Distinguishes true interruptions ("stop", "hold up") from backchannels ("okay", "right")
- **Filler Injection**: Custom streaming model that converts formal LLM output into conversational speech by injecting natural fillers in real-time
- **Audio Filtering**: Two models — one for ambient noise, one for background speech isolation
- **Emotion Detection**: Real-time audio analysis feeding emotional context to LLM

### Prompt Structure (Official Guide)
Four-section structure:

```
1. IDENTITY — persona, role, name
2. STYLE — tone, communication guidelines  
3. RESPONSE GUIDELINES — formatting, structural rules
4. TASK & GOALS — objectives, step-by-step instructions
```

Key techniques:
- **Filler words**: Include "uh," "um," "well" in prompts for naturalness
- **Stuttering**: Use repeated letters: "I-I-I don't know"
- **Pauses**: Use ellipses "..."
- **Numbers**: Spell out — "Four Thirty PM", "January Twenty Four"
- **Emotional tone**: Capital letters + exclamation marks shape personality
- **Turn markers**: Use `<wait for user response>` to indicate pause points
- **Silent transfers**: "Do not send any text response, silently call the transfer tool"
- **ASR error handling**: Never say "transcription error" — use "didn't catch that", "some noise", "you're coming through choppy"

### Speech Configuration (Critical for OptiBot)

**Start Speaking Plan:**
```json
{
  "startSpeakingPlan": {
    "waitSeconds": 0.4,           // default, reduce for snappier
    "smartEndpointingPlan": {
      "provider": "livekit",       // best for English
      // OR "vapi"                 // recommended for non-English (FRENCH!)
      "waitFunction": "200 + 8000 * x"  // probability -> ms mapping
    }
  }
}
```

**Stop Speaking Plan:**
```json
{
  "stopSpeakingPlan": {
    "numWords": 0,        // words before stopping (0 = immediate)
    "voiceSeconds": 0.2,  // duration user must speak before agent stops
    "backoffSeconds": 1   // wait before resuming after interruption
  }
}
```

**For French conversations**: Use `"vapi"` as smart endpointing provider (their docs explicitly recommend this for non-English).

### Lowest Latency Configuration (~465ms)
From AssemblyAI's guide:

| Component | Provider | Latency |
|-----------|----------|---------|
| STT | AssemblyAI Universal-Streaming (formatTurns: false) | 90ms |
| LLM | Groq Llama 4 Maverick 17B | 200ms |
| TTS | ElevenLabs Flash v2.5 (optimizeStreamingLatency: 4) | 75ms |
| **Pipeline Total** | | **365ms** |
| Network (Web) | WebRTC | +100ms |
| Network (Phone) | Twilio/Vonage | +600ms+ |

**Critical insight**: Default turn detection settings add 1500ms to a 365ms pipeline. The `onNoPunctuationSeconds: 1.5` default is the killer.

### Backchannel Handling (Current State)
The `backchannelingEnabled` boolean was **deprecated October 2024**. Now handled through:
- Smart endpointing plan (detects backchannels automatically)
- `stopSpeakingPlan.numWords` — set higher to prevent acknowledgments from interrupting
- Krisp audio-based provider detects prosodic features (intonation, pitch, rhythm)

---

## 2. Retell AI — Deep Dive

### WebSocket Protocol (Complete)
Retell uses a **WebSocket-based custom LLM integration**. Your server connects at `wss://{your-server}/{call_id}`.

**Events from Retell -> Your Server:**
1. `ping_pong` — keepalive every 2s
2. `call_details` — once at start (call type, from/to numbers, metadata)
3. `update_only` — transcript updates + turn-taking signals (no response needed)
4. `response_required` — LLM must generate response
5. `reminder_required` — user been silent, send nudge

**Events from Your Server -> Retell:**
1. `config` — sent on connect (auto_reconnect, call_details, transcript_with_tool_calls)
2. `ping_pong` — response to keepalive
3. `response` — streamed LLM response (content, content_complete, end_call, transfer_number)
4. `agent_interrupt` — force-interrupt current speech
5. `update_agent` — dynamically change agent behavior mid-call
6. `tool_call_invocation` / `tool_call_result` — function calling
7. `metadata` — forward custom data to frontend

**Key `update_agent` parameters (adjustable mid-call):**
```json
{
  "response_type": "update_agent",
  "agent_config": {
    "responsiveness": 0.5,              // 0-1, higher = faster
    "interruption_sensitivity": 0.5,     // 0-1, higher = easier interrupt
    "reminder_trigger_ms": 5000,         // silence before reminder
    "reminder_max_count": 3              // max reminders (0 = disabled)
  }
}
```

### Retell's Custom LLM Pattern (Production Code)

The key pattern from their Python demo:

```python
# server.py — FastAPI WebSocket handler
@app.websocket("/llm-websocket/{call_id}")
async def websocket_handler(websocket: WebSocket, call_id: str):
    await websocket.accept()
    llm_client = LlmClient()
    
    # 1. Send config
    config = ConfigResponse(response_type="config", config={
        "auto_reconnect": True, "call_details": True,
    })
    await websocket.send_json(config.__dict__)
    
    # 2. Send greeting
    first_event = llm_client.draft_begin_message()
    await websocket.send_json(first_event.__dict__)
    
    # 3. Handle messages with response_id tracking
    response_id = 0
    async def handle_message(request_json):
        nonlocal response_id
        if request_json["interaction_type"] == "response_required":
            response_id = request_json["response_id"]
            async for event in llm_client.draft_response(request):
                await websocket.send_json(event.__dict__)
                if request.response_id < response_id:
                    break  # new response needed, abandon this one
    
    async for data in websocket.iter_json():
        asyncio.create_task(handle_message(data))
```

**Critical pattern**: The `response_id` comparison allows **abandoning stale responses** when a new one is requested (user interrupted).

### Retell's System Prompt Template

```
## Style Guardrails
- [Be concise] Short responses, one question at a time
- [Do not repeat] Rephrase, don't echo transcript
- [Be conversational] Everyday language, filler words, short prose
- [Reply with emotions] Humor, empathy, surprise
- [Be proactive] End with questions or next steps

## Response Guidelines  
- [Overcome ASR errors] Guess intent, use "didn't catch that" / "some noise"
- [Always stick to your role] Steer back to goal
- [Create smooth conversation] Fit into live calling context
```

### Latency Numbers
- Average: **620ms** for critical interactions
- Target: sub-800ms end-to-end
- Uses WebRTC (not PSTN) to avoid 150-700ms phone network overhead

---

## 3. Bland AI — Deep Dive

### Conversational Pathways
Node-based conversation flow system where each node represents an action or response:
- **Dynamic nodes**: AI-generated responses
- **Static nodes**: Scripted responses
- **Multi-pathway routing**: Switch between workflows (e.g., Pathway A for booking, Pathway B for support)
- **Loop conditions**: Ensure required info is collected before proceeding
- **Webhook integration**: Custom API calls at each step
- **Warm transfers**: With full conversation context to live agents

### Memory System (Cross-Channel)
Bland's memory stores per-contact:
- **Facts**: structured key-value (name, preferences, account details)
- **Summary**: rolling plain-text overview of past conversations
- **Open items**: action items and follow-ups
- **Entities**: structured objects (orders, appointments, tickets)
- **Recent messages**: sliding window of latest exchanges

**Key design decisions:**
- Contacts matched by phone number, email, or external ID
- Memory persists across channels (voice + SMS)
- Each persona maintains separate memory (no cross-contamination)
- Automatic update after each interaction
- API access: List contacts, Get Memory Context, Get Memory Changes, Update Facts, Reset Contact Memory

### Applicability to OptiBot
Bland's memory model maps directly to our mutuelle tracking needs:
- **Facts** = mutuelle name, phone number, IVR path, tiers payant status
- **Entities** = prior call results, quotes, patient references  
- **Open items** = pending callbacks, unresolved queries
- **Summary** = what happened in previous calls to same mutuelle

---

## 4. Voice AI Pipeline — The 300ms Budget

### Latency Breakdown (Production Targets)

| Stage | Target | Notes |
|-------|--------|-------|
| STT Finalization | 50-100ms | Confirming final transcript |
| LLM First Token | 100-200ms | TTFT is the bottleneck |
| TTS First Byte | 50-80ms | First audio chunk |
| Transport (WebRTC) | 20-50ms | Best case |
| Transport (PSTN) | 150-700ms | Phone network overhead |
| **Total (WebRTC)** | **220-430ms** | |
| **Total (Phone)** | **350-1080ms** | |

### Model Selection Impact on TTFT

| Model | TTFT | Notes |
|-------|------|-------|
| Groq llama-3.3-70b | 50-100ms | Fastest for speed-critical |
| gpt-4o-mini | 120-200ms | Good balance |
| GPT-4o | 250-500ms | Exceeds budget |
| Mistral small | ~100ms | Good for French JSON |

### Streaming Architecture
All three stages run concurrently:
1. STT emits **partial transcripts** while user still speaking
2. LLM starts generating tokens with **partial context**
3. TTS converts **each token chunk** to audio as it arrives

Frame-based processing: small typed objects flow through processors, each consuming one frame type and emitting the next.

### Turn Detection
- **Semantic turn detection** reduces false interruptions by 40-60% vs. VAD alone
- Analyzes transcript content, not just silence
- Interruption handling must clear pipeline in **<100ms**

---

## 5. RAG in Voice Agents — The Latency Problem

### The Problem
Traditional RAG adds 50-300ms for vector DB query alone. Voice agents need sub-200ms total response. RAG can consume the ENTIRE latency budget.

### VoiceAgentRAG: Dual-Agent Architecture (arxiv 2603.02206)

**Fast Talker (Foreground)**:
- Checks in-memory FAISS semantic cache first (<1ms lookup)
- Falls back to vector DB only on cache miss
- Auto-caches results for future queries

**Slow Thinker (Background)**:
- Runs asynchronously during inter-turn delays (3-7 seconds)
- Predicts 3-5 likely follow-up topics using LLM
- Pre-fetches relevant chunks into cache

**Performance:**
| Metric | Value |
|--------|-------|
| Cache hit latency | 0.35ms |
| Vector DB latency | 110.4ms (Qdrant Cloud) |
| Speedup on cache hit | 316x |
| Overall cache hit rate | 75% |
| Warm turn hit rate (turns 5+) | 86% |
| Cumulative savings | 16.5s over 150 queries |

**Cache design:**
- FAISS IndexFlatIP indexed by **document embeddings** (not query embeddings)
- Cosine similarity threshold >= 0.40
- TTL: 300 seconds
- Max capacity: 2000 entries, LRU eviction
- Rate limiting: 0.5s min between Slow Thinker predictions

### Practical RAG Lessons (LiveKit Implementation)

1. **System prompt vs. RAG**: Keep prompts focused on persona/safety/flow. Domain knowledge goes in retrieval layer only.
2. **Single-purpose tasks**: Use tight, focused prompts per task, not one giant prompt
3. **Explicit retrieval**: Never use opaque "file search" features. Control retrieval calls explicitly for failure handling.
4. **Embedding placement**: Never run embedding models inside media containers (causes timeouts). Use external services.
5. **Smart chunking**: Organize around single topics or Q&A pairs, not arbitrary splits
6. **Error handling**: If retrieval fails, fall back to safe pre-authored response or human handoff
7. **Cache short windows**: Cache retrieval results to eliminate repeated searches within same turn
8. **Critical field validation**: For emails/phones, enforce via orchestrator logic, not LLM alone

---

## 6. Key Patterns for OptiBot v2

### Pattern 1: Hold Phrases WITHOUT Hardcoded Lists

**How production platforms solve this:**

VAPI and Retell do NOT use keyword lists. They use:

1. **Filler Injection Model** (VAPI): A streaming model that converts formal LLM output into conversational speech, injecting fillers in real-time. The LLM never outputs "je verifie" — the filler model inserts appropriate conversational markers.

2. **LLM-Native Hold Phrases** (Retell): The system prompt instructs the LLM to naturally use hold phrases as part of its conversational style. From Retell's template:
```
Be conversational. Speak like a human — use everyday language.
Occasionally add filler words while keeping prose short.
```

3. **For OptiBot**: Instead of detecting "je verifie" in output, the approach should be:
```python
# In the system prompt:
"""
Quand tu dois chercher une information ou appeler un outil,
annonce naturellement ce que tu fais:
- "Laissez-moi regarder ca..."  
- "Je consulte le dossier..."
- "Un instant, je verifie..."

Varie tes formulations. Ne repete jamais la meme phrase d'attente
deux fois de suite. Utilise des marqueurs conversationnels naturels
comme "alors", "donc", "voyons voir".
"""

# In the pipeline: use tool_call events to trigger hold audio
# When LLM calls a tool -> play ambient hold sound + short phrase
# When tool returns -> resume with result
```

### Pattern 2: Conversation Memory Across Calls

**Bland's model adapted for OptiBot:**
```python
# Per-mutuelle memory structure
mutuelle_memory = {
    "facts": {
        "name": "Harmonie Mutuelle",
        "phone": "0800 123 456",
        "ivr_path": ["1", "3", "2"],  # button sequence
        "tiers_payant": True,
        "avg_hold_time_seconds": 180,
        "agent_language": "fr",
    },
    "summary": "Dernier appel: remboursement verres progressifs OK, "
               "delai 5 jours. Agent cooperative.",
    "open_items": [
        "Verifier plafond annuel optique patient Dupont"
    ],
    "entities": {
        "last_call": {"date": "2026-04-01", "result": "success", "duration": 240},
        "quotes": [{"ref": "Q-2026-0042", "amount": 450.00, "status": "pending"}]
    },
    "recent_interactions": [
        {"role": "agent", "content": "Le remboursement est de 200 euros..."},
        # sliding window, last 10 exchanges
    ]
}
```

**Storage**: Supabase pgvector (already planned). Pre-load at call start, update at call end.

### Pattern 3: French-Optimized Prompt Structure

Based on VAPI + Retell patterns, adapted for French:

```python
OPTIBOT_SYSTEM_PROMPT = """
## Identite
Tu es OptiBot, un assistant telephonique professionnel pour opticiens.
Tu appelles les mutuelles pour verifier les prises en charge optiques.

## Style de Communication
- Parle comme un(e) assistant(e) humain(e) professionnel(le)
- Utilise un registre soutenu mais naturel (vouvoiement systematique)
- Phrases courtes: maximum 15 mots par reponse
- Une seule question a la fois
- Marque des pauses naturelles avec "..."
- Utilise des marqueurs conversationnels: "alors", "tres bien", "je comprends"

## Gestion des Erreurs de Transcription
- Ne jamais mentionner "erreur de transcription"
- Utilise: "Excusez-moi, je n'ai pas bien entendu"
- Ou: "Il y a un peu de bruit sur la ligne, pourriez-vous repeter?"
- Si tu devines le sens, confirme: "Si je comprends bien, vous dites que..."

## Gestion de l'Attente
Quand tu utilises un outil ou cherches une information:
- Annonce naturellement: "Je consulte le dossier, un instant..."
- Varie: "Laissez-moi verifier cela..." / "Je regarde tout de suite..."
- Ne repete JAMAIS la meme phrase d'attente consecutivement

## Objectif de l'Appel
{call_objective}

## Contexte Patient
{patient_context}

## Memoire Mutuelle
{mutuelle_memory}
"""
```

### Pattern 4: RAG During Active Calls (Dual-Agent for OptiBot)

```python
import asyncio
from dataclasses import dataclass
import faiss
import numpy as np

@dataclass
class CacheEntry:
    chunks: list[str]
    embeddings: np.ndarray
    ttl: float  # seconds
    created_at: float

class MutuelleRAGCache:
    """VoiceAgentRAG pattern adapted for mutuelle knowledge."""
    
    def __init__(self, embedding_dim=1536, max_entries=500, ttl=300):
        self.index = faiss.IndexFlatIP(embedding_dim)
        self.entries: dict[int, CacheEntry] = {}
        self.max_entries = max_entries
        self.ttl = ttl
    
    async def get(self, query_embedding: np.ndarray, threshold=0.40, top_k=3):
        """Fast Talker: sub-ms cache lookup."""
        if self.index.ntotal == 0:
            return None
        scores, indices = self.index.search(query_embedding.reshape(1, -1), top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if score >= threshold and idx in self.entries:
                results.append(self.entries[idx].chunks)
        return results if results else None
    
    async def prefetch(self, conversation_history: str, llm_client):
        """Slow Thinker: predict next questions, prefetch from Supabase."""
        predictions = await llm_client.predict_next_topics(
            conversation_history,
            prompt="Predict 3-5 likely follow-up questions about mutuelle coverage"
        )
        for topic in predictions:
            chunks = await self.vector_db.search(topic)
            embeddings = await self.embed(chunks)
            self.put(chunks, embeddings)


class CallRAGOrchestrator:
    """Orchestrates Fast Talker + Slow Thinker during active call."""
    
    def __init__(self, cache: MutuelleRAGCache):
        self.cache = cache
        self.prefetch_task = None
    
    async def on_user_turn(self, transcript: str):
        """Called when user finishes speaking."""
        # Fast path: check cache
        embedding = await self.embed(transcript)
        cached = await self.cache.get(embedding)
        if cached:
            return cached  # 0.35ms
        
        # Slow path: query Supabase pgvector
        results = await self.vector_db.search(transcript)  # ~110ms
        await self.cache.put(results)
        return results
    
    async def on_agent_speaking(self, conversation_so_far: str):
        """Called while agent is speaking — use dead time for prefetch."""
        if self.prefetch_task and not self.prefetch_task.done():
            return  # already prefetching
        self.prefetch_task = asyncio.create_task(
            self.cache.prefetch(conversation_so_far, self.llm)
        )
```

### Pattern 5: Preventing Robotic Sound

All three platforms converge on these techniques:

1. **Prompt-level**: Include filler words, emotional instructions, varied vocabulary
2. **Pipeline-level**: Filler injection model (VAPI), or TTS prosody control
3. **Turn-taking**: Semantic endpointing (not silence-based) prevents unnatural pauses
4. **Response length**: Keep under 10 words per utterance for conversational feel
5. **ASR error masking**: Never expose transcription artifacts to user
6. **Dynamic pacing**: Adjust `responsiveness` parameter based on conversation state (Retell's `update_agent`)
7. **Background audio**: Office ambiance on phone calls (VAPI default)

**For French specifically:**
- Use VAPI's `"vapi"` endpointing provider (designed for non-English)
- Vouvoiement creates natural formality without sounding robotic
- French conversational markers ("alors", "bon", "voila", "du coup") are essential
- Numbers must be spelled out in French format ("quatre cent cinquante euros")

---

## 7. Architecture Comparison

| Feature | VAPI | Retell AI | Bland AI |
|---------|------|-----------|----------|
| Integration | REST API + SDKs | WebSocket custom LLM | REST API + Pathways |
| Latency | ~465ms achievable | ~620ms average | Not published |
| Turn-taking | Fusion audio-text model | Proprietary model | Not documented |
| Backchannels | Deprecated flag, now auto | Via `interruption_sensitivity` | Not documented |
| Memory | Context compression | Via custom LLM | Built-in cross-channel |
| RAG | Via tool calls | Via custom LLM | Via knowledge base |
| French support | Yes (dedicated endpointing) | Yes | Yes |
| Customization | Moderate (config-based) | High (full LLM control) | Moderate (pathway-based) |
| Price model | Per-minute | Per-minute | Per-minute |

---

## 8. Recommended Architecture for OptiBot v2

Based on this research, the optimal architecture combines:

1. **Retell-style WebSocket protocol** for maximum LLM control (we need custom logic for IVR navigation, hold detection, mutuelle-specific flows)
2. **VAPI-style prompt structure** (Identity/Style/Response/Task) adapted for French
3. **Bland-style memory system** for per-mutuelle context persistence in Supabase
4. **VoiceAgentRAG dual-agent pattern** for sub-ms RAG retrieval during calls
5. **VAPI's speech config patterns** for French-optimized endpointing

### Latency Budget for OptiBot v2

| Component | Target | Provider |
|-----------|--------|----------|
| STT | 80ms | Deepgram Nova-3 (French) |
| LLM (main) | 150ms | Groq llama-3.3-70b or Mistral small |
| LLM (classifiers) | 30ms | Groq llama-3.1-8b-instant |
| TTS | 70ms | Cartesia Sonic-3 |
| RAG (cache hit) | <1ms | FAISS in-memory |
| RAG (cache miss) | 50ms | Supabase pgvector (local region) |
| Transport | 150-700ms | Twilio SIP (unavoidable) |
| **Total (cache hit)** | **~480ms + transport** | |
| **Total (cache miss)** | **~530ms + transport** | |

---

## Sources

- [VAPI Prompting Guide](https://docs.vapi.ai/prompting-guide)
- [VAPI Speech Configuration](https://docs.vapi.ai/customization/speech-configuration)
- [VAPI Orchestration Models](https://docs.vapi.ai/how-vapi-works)
- [AssemblyAI: Lowest Latency Voice Agent in VAPI](https://www.assemblyai.com/blog/how-to-build-lowest-latency-voice-agent-vapi)
- [Voice AI Pipeline: 300ms Budget](https://www.channel.tel/blog/voice-ai-pipeline-stt-tts-latency-budget)
- [Retell AI WebSocket Protocol](https://docs.retellai.com/api-references/llm-websocket)
- [RetellAI/retell-custom-llm-python-demo](https://github.com/RetellAI/retell-custom-llm-python-demo)
- [Bland AI Memory](https://docs.bland.ai/tutorials/memories)
- [Bland AI Conversational Pathways](https://www.bland.ai/product/conversational-pathways)
- [VoiceAgentRAG: Dual-Agent Architecture (arXiv 2603.02206)](https://arxiv.org/html/2603.02206)
- [Lessons from RAG in Real-Time Voice Agent (LiveKit)](https://medium.com/@jorge.jarne/lessons-from-implementing-rag-in-a-real-time-voice-agent-livekit-43f0689bf565)
- [AI Voice Agents in 2025: Comprehensive Guide](https://dev.to/kaymen99/ai-voice-agents-in-2025-a-comprehensive-guide-3kl)
- [VapiAI/examples (GitHub)](https://github.com/VapiAI/examples)

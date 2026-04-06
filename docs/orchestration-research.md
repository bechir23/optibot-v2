# Orchestration Framework Research for OptiBot v2

**Date:** 2026-04-06
**Context:** Outbound French voice agent calling mutuelles (health insurance)
**Pipeline:** IVR navigation -> hold detection -> conversation -> data extraction -> call summary

---

## Executive Recommendation

**Use LiveKit native agent handoffs. Do NOT add LangGraph or CrewAI.**

LiveKit's built-in Agent/AgentSession/Workflows system is sufficient and optimal for OptiBot's use case. Adding LangGraph or CrewAI would introduce 3-6 seconds of latency overhead, add dependency complexity, and solve problems you don't have. Your current architecture (IVRNavigatorAgent -> OutboundCallerAgent handoff) already uses the correct pattern.

---

## Framework-by-Framework Analysis

### 1. LangGraph

**What it does well:**
- Complex reasoning graphs with conditional branching, cycles, checkpointing
- State persistence across nodes with typed state schemas
- Human-in-the-loop patterns (interrupt/resume)
- Excellent for text-based multi-step workflows

**Voice agent integration:**
- Works via an adapter pattern: LangGraph runs as a separate HTTP server, LiveKit connects to it via a custom LLM adapter (`langgraph.py` bridge file)
- Thread IDs in participant metadata maintain conversation continuity
- Example repo: `ahmad2b/langgraph-voice-call-agent`

**Critical problems for OptiBot:**
- **Latency killer:** LangGraph adds an HTTP hop (LiveKit -> LangGraph server -> LLM -> back). Forum reports show 5-8 second latency vs target of <800ms. The root cause remains unresolved in the LangChain community.
- **Architectural mismatch:** LangGraph treats voice as a wrapper around text-based reasoning. Your IVR navigator needs real-time DTMF sending, hold detection, and sub-second audio processing -- none of which benefit from a graph abstraction.
- **Unnecessary complexity:** Your agent handoff (IVR -> Conversation) is a simple linear transition, not a complex graph with cycles. LangGraph's power (conditional branching, loops, checkpointing) is overkill.
- **Deployment burden:** Requires running a separate LangGraph server process alongside LiveKit agent server.

**Verdict: REJECT for voice pipeline. Consider only if adding complex post-call text analysis workflows.**

### 2. CrewAI

**What it does well:**
- Role-based multi-agent collaboration (mimics human teams)
- Sequential and hierarchical execution strategies
- 45.9k GitHub stars, used by 60% of Fortune 500
- Good for batch processing, content generation, research tasks

**Voice agent integration:**
- **None.** CrewAI has zero voice-specific features. No STT/TTS pipeline support, no real-time streaming, no WebRTC integration.
- CrewAI agents are text-based workers designed for async batch tasks (e.g., "research this topic, then write a report, then review it").
- "Real-time" in CrewAI means real-time tracing/monitoring of agent execution, not real-time audio processing.

**Critical problems for OptiBot:**
- No audio pipeline support whatsoever
- Execution model is request-response, not streaming
- Would require building an entire bridge layer to LiveKit (more work than just using LiveKit native)
- Cannot handle DTMF, hold detection, or interruption management

**Verdict: REJECT completely. Wrong tool for voice agents.**

### 3. LiveKit Native Multi-Agent (RECOMMENDED)

**What it does well:**
- Purpose-built for real-time voice AI
- Native WebRTC with sub-300ms audio transport
- Agent handoffs with `chat_ctx` preservation
- `userdata` for cross-agent state persistence
- Workflows system for complex multi-step operations
- MCP integration for external tool access
- SIP/DTMF support built-in
- Preemptive generation for lower perceived latency

**How agent handoff works (from `livekit-examples/multi-agent-python`):**

```python
class IVRNavigatorAgent(Agent):
    @function_tool()
    async def human_answered(self, ctx: RunContext) -> tuple:
        """Hand off to conversation agent when human detected."""
        caller = OutboundCallerAgent(
            chat_ctx=self.chat_ctx,  # preserve conversation history
            **self.caller_kwargs
        )
        return caller, "Humain detecte, passage en mode conversation."

class OutboundCallerAgent(Agent):
    @function_tool()
    async def escalate_to_supervisor(self, ctx: RunContext) -> tuple:
        """Escalate to a supervisor agent if needed."""
        summary = await summarize_session(self.session.llm, self.chat_ctx)
        chat_ctx = ChatContext()
        chat_ctx.add_message(role="system", content=f"Prior conversation: {summary}")
        return SupervisorAgent(chat_ctx=chat_ctx), "Escalade vers le superviseur."
```

**Context preservation patterns:**
1. **Full copy:** `chat_ctx=self.chat_ctx` -- new agent sees entire conversation
2. **Instructions excluded:** `chat_ctx=self.chat_ctx.copy(exclude_instructions=True)` -- history without prior agent's system prompt
3. **Summarized:** Generate summary via LLM, pass condensed context
4. **Shared userdata:** `@dataclass` with call state accessible to all agents

**MCP integration for external tools:**

```python
session = AgentSession(
    stt="deepgram/nova-3-general",
    llm="openai/gpt-4.1-mini",
    tts="cartesia/sonic-2:voice-id",
    mcp_servers=[mcp.MCPServerHTTP(url="https://your-mcp-server/mcp")],
)
```

MCP tools are auto-discovered by the LLM -- the agent can call any tool exposed by the MCP server during voice conversation.

**Workflows (for complex multi-step operations):**
- **Agents:** Long-lived, hold session control, define instructions/tools, can transfer to other agents
- **Tasks:** Short-lived, run to completion, return typed results
- **TaskGroups:** Ordered sequences with step revisitation

**What OptiBot already uses correctly:**
- IVRNavigatorAgent with DTMF tools -> handoff via `human_answered()` returning tuple
- OutboundCallerAgent with function tools for data extraction
- Shared state via constructor kwargs (rag_context, call_state_store, etc.)

**What to add:**
- Formalize `userdata` dataclass for cross-agent state (instead of passing kwargs)
- Add context summarization for long calls before any handoff
- Consider MCP server for mutuelle database access (RAG, memory)

**Verdict: ALREADY USING. Enhance, don't replace.**

### 4. Pipecat Flows

**What it does well:**
- Conversation as a state machine (graph of nodes)
- Each node scopes the LLM to specific task + specific tools only
- Prevents context pollution across conversation phases
- Visual flow editor at flows.pipecat.ai
- Examples: food ordering, patient intake, insurance quotes, warm transfers

**Node architecture:**

```python
# Each node defines: role messages, task messages, available functions
node_config = {
    "name": "collect_dossier_info",
    "role_messages": [{"role": "system", "content": "Tu es un gestionnaire tiers payant..."}],
    "task_messages": [{"role": "system", "content": "Collecte le numero de dossier et le montant."}],
    "functions": [
        {
            "name": "record_dossier",
            "description": "Record dossier reference and amount",
            "handler": record_dossier_handler,
            "transition_to": "verify_info"
        }
    ]
}
```

**Critical problems for OptiBot:**
- **Different transport layer:** Pipecat uses Daily.co for WebRTC transport, not LiveKit. You'd have to rewrite your entire transport and SIP integration.
- **Your project is already on LiveKit.** Switching to Pipecat means abandoning all LiveKit-specific code (DTMF publishing, SIP trunk integration, LiveKit Cloud deployment).
- **Pipecat's state machine is essentially what LiveKit Workflows provides.** The concepts (scoped tools per phase, context reset on transition) can be implemented in LiveKit agents without Pipecat.

**What to steal from Pipecat Flows (implement in LiveKit):**
- **Scoped tool access per agent:** Each agent should only have the tools relevant to its phase. Your IVRNavigatorAgent already does this (only press_digit, human_answered, voicemail_detected).
- **Task messages that reset per phase:** When handing off, use `exclude_instructions=True` and set fresh instructions on the new agent.
- **Node-based conversation design:** Think of each Agent subclass as a "node" in the conversation flow.

**Verdict: REJECT as framework. ADOPT its design philosophy within LiveKit agents.**

### 5. Google A2A (Agent-to-Agent) Protocol

**What it is:**
- Open protocol for inter-agent communication (announced April 2025)
- Currently at spec v0.3 (draft stage), production-ready version planned for 2026
- gRPC support, security cards, Python SDK
- Supported by 50+ partners (Atlassian, LangChain, Salesforce, SAP, etc.)

**Voice relevance:**
- A2A is designed for agents that "don't share memory, tools, or context" -- cross-organization agent collaboration
- Audio/video mid-conversation support is listed as "under investigation" (not implemented)
- Focus is enterprise workflows, not real-time voice pipelines

**Critical problems for OptiBot:**
- Spec is still draft -- not production-ready
- Designed for cross-organization agent communication, not intra-application agent coordination
- No voice-specific features
- Massive overhead for what is essentially function calling between your own agents

**When A2A becomes relevant:**
- If mutuelles themselves deploy A2A-compatible agents that OptiBot could negotiate with directly (machine-to-machine calls instead of voice calls). This is years away.

**Verdict: REJECT for now. Monitor for future mutuelle API integration.**

### 6. MCP (Model Context Protocol) for Voice Agents

**What it does:**
- Standard protocol for LLMs to access external tools/data
- LiveKit has native MCP support (Python only, `mcp_servers` param on AgentSession)
- Tools are auto-discovered -- LLM sees all MCP-exposed tools and can call them during conversation

**How it works with LiveKit:**

```python
from livekit.agents import AgentSession, mcp

session = AgentSession(
    stt="deepgram/nova-3-general",
    llm="openai/gpt-4.1-mini",
    tts="cartesia/sonic-2:voice-id",
    mcp_servers=[
        mcp.MCPServerHTTP(url="http://localhost:8080/mcp"),  # mutuelle memory server
    ],
)
```

**Concrete value for OptiBot:**
- Build an MCP server that exposes: mutuelle memory lookup, RAG retrieval, dossier status, IVR tree lookup
- The voice agent can dynamically query mutuelle knowledge during conversation
- Separates data access logic from agent conversation logic
- Same MCP server can be reused by dashboard, API, or other agents

**Implementation plan:**
1. Create FastAPI MCP server exposing: `lookup_mutuelle_memory`, `get_ivr_tree`, `search_past_calls`, `get_dossier_status`
2. Wire it into AgentSession via `mcp_servers` param
3. Agent's LLM automatically discovers and uses these tools

**Verdict: ADOPT. Build an MCP server for mutuelle data access.**

### 7. Azure Agentic Call Center

**What it is:**
- Sample app using "Vanilla AI Agents" framework on Azure
- Microservice architecture: Frontend (Chainlit/WhatsApp/Phone) -> FastAPI backend -> Agent microservice
- Uses Azure Communication Services for telephony
- Agents run in Azure Container Apps, data in Cosmos DB + AI Search

**Architecture pattern:**
- Agents are a separate microservice (independently scalable)
- HTTP-based orchestration between API layer and agents
- Multi-channel: web chat, WhatsApp, phone all hit same agent logic
- RAG via Azure AI Search

**What to learn:**
- Separating agent logic into its own microservice is a good pattern for scaling
- Multi-channel support (same agent answers web chat or phone) is valuable long-term
- But their architecture adds HTTP hops that hurt voice latency

**Critical problems for OptiBot:**
- Azure-specific (Cosmos DB, Azure Communication Services, Azure OpenAI)
- HTTP-based agent orchestration adds latency unacceptable for voice
- No real-time audio pipeline -- they use Azure Communication Services for voice, not LiveKit

**Verdict: REJECT as framework. Note microservice pattern for future scaling.**

---

## Recommended Architecture for OptiBot v2

### What You Have (Already Correct)

```
SIP Trunk -> LiveKit Cloud -> Room -> AgentSession
                                         |
                                    IVRNavigatorAgent
                                    (DTMF tools, menu navigation)
                                         |
                                    [human_answered() handoff]
                                         |
                                    OutboundCallerAgent
                                    (conversation tools, data extraction)
                                         |
                                    [call ends -> summary + RAG writeback]
```

### What to Add

#### 1. Formalize Agent State with UserData

```python
@dataclass
class CallSessionData:
    call_id: str = ""
    tenant_id: str = "default"
    mutuelle: str = ""
    patient_name: str = ""
    patient_dob: str = ""
    nir: str = ""
    dossier_ref: str = ""
    montant: float = 0.0
    dossier_type: str = "optique"
    
    # Runtime state
    svi_path: list[str] = field(default_factory=list)
    phase: str = "ivr"  # ivr | hold | conversation | summary
    hold_count: int = 0
    extracted_data: dict = field(default_factory=dict)
    
    # RAG context loaded pre-call
    rag_context: dict = field(default_factory=dict)
    known_ivr_tree: dict = field(default_factory=dict)
    
    # Services (injected at session start)
    call_state_store: Any = None
    rag_service: Any = None

session = AgentSession[CallSessionData](
    userdata=CallSessionData(
        call_id=ctx.room.name,
        tenant_id=tenant_id,
        mutuelle=mutuelle,
        ...
    ),
    stt=stt_model,
    llm=llm_model,
    tts=tts_model,
    vad=vad_model,
)
```

#### 2. Add a HoldAgent for Long Waits

```python
class HoldWaitAgent(Agent):
    """Monitors hold music, plays periodic comfort messages."""
    
    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions="""Tu es en attente. Ecoute la musique d'attente.
            Si tu entends un humain parler (pas de la musique), appelle human_returned.
            Ne parle pas pendant l'attente sauf si ca fait plus de 3 minutes.""",
            chat_ctx=chat_ctx,
        )
    
    @function_tool()
    async def human_returned(self, ctx: RunContext[CallSessionData]) -> tuple:
        """Human operator came back on the line."""
        ctx.userdata.phase = "conversation"
        return OutboundCallerAgent(
            chat_ctx=self.chat_ctx.copy(exclude_instructions=True)
        ), "L'agent est revenu, reprise de la conversation."
    
    @function_tool()
    async def hold_timeout(self, ctx: RunContext[CallSessionData]) -> str:
        """Hold has been too long, hang up and reschedule."""
        ctx.userdata.phase = "timeout"
        return "Attente trop longue. Rappeler plus tard."
```

#### 3. Build MCP Server for Mutuelle Data

```python
# mcp_server.py -- FastAPI MCP server
from fastapi import FastAPI
from livekit.agents.mcp import MCPServerHTTP

@mcp_tool()
async def lookup_mutuelle_memory(mutuelle_name: str) -> dict:
    """Get known info about this mutuelle: IVR tree, hold times, tips."""
    return await mutuelle_memory.get(mutuelle_name)

@mcp_tool()
async def search_past_calls(mutuelle: str, topic: str) -> list:
    """Search past call outcomes with this mutuelle."""
    return await rag_service.search(mutuelle=mutuelle, query=topic, limit=3)

@mcp_tool()
async def get_dossier_status(dossier_ref: str) -> dict:
    """Check current status of a reimbursement dossier."""
    return await supabase.get_dossier(dossier_ref)
```

Wire into session:
```python
session = AgentSession[CallSessionData](
    ...
    mcp_servers=[mcp.MCPServerHTTP(url=f"http://localhost:{MCP_PORT}/mcp")],
)
```

#### 4. Context Summarization for Long Calls

```python
async def summarize_for_handoff(session_llm, chat_ctx: ChatContext) -> str:
    """Summarize conversation before handoff to keep context window clean."""
    summary_ctx = ChatContext()
    summary_ctx.add_message(
        role="system",
        content="Resume cette conversation telephonique en 3 phrases. "
                "Inclus: qui a parle, ce qui a ete dit, et le statut du dossier."
    )
    for item in chat_ctx.items:
        if item.role in ("user", "assistant"):
            text = (item.text_content or "").strip()
            if text:
                summary_ctx.add_message(role="user", content=f"{item.role}: {text}")
    
    response = await session_llm.chat(chat_ctx=summary_ctx).collect()
    return response.text.strip() if response.text else ""
```

---

## Decision Matrix

| Criterion                          | LiveKit Native | LangGraph | CrewAI | Pipecat Flows |
|------------------------------------|---------------|-----------|--------|---------------|
| Voice latency (<800ms)             | YES           | NO (5-8s) | N/A    | YES           |
| LiveKit Cloud compatible           | YES           | Adapter   | NO     | NO (Daily.co) |
| SIP/DTMF support                   | Native        | Via LK    | NO     | Via Daily     |
| Agent handoff with context         | Native        | Via HTTP  | NO     | Native        |
| MCP tool integration               | Native        | Native    | NO     | NO            |
| Real-time streaming                | Native        | Adapter   | NO     | Native        |
| Scoped tools per agent             | YES           | YES       | YES    | YES           |
| State persistence                  | userdata+Redis| Checkpoints| Memory | FlowManager  |
| Already in OptiBot codebase        | YES           | NO        | NO     | NO            |
| Additional deployment complexity   | None          | +1 server | +1 dep | Full rewrite  |

---

## Final Answer

**Do NOT add LangGraph or CrewAI on top of LiveKit.**

Your current architecture is the correct one. LiveKit's native Agent + AgentSession + function_tool handoff pattern is purpose-built for exactly your use case. The three concrete improvements to make:

1. **Formalize CallSessionData as a typed userdata dataclass** -- replaces kwargs passing between agents
2. **Add MCP server for mutuelle data access** -- clean separation of data layer from agent logic
3. **Add HoldWaitAgent** -- dedicated agent for hold detection/monitoring instead of mixing it into OutboundCallerAgent

These are incremental improvements to your existing architecture, not framework replacements.

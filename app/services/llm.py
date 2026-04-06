"""Dual-LLM service — Microsoft call-center-ai pattern.

Primary: Mistral (French-native, best comprehension)
Fallback: Groq llama-3.1-8b-instant (fast, free, for simple turns + IVR)

Production safeguards:
- json-repair on every LLM response (Microsoft pattern)
- tiktoken context window management (truncate at budget)
- max_tokens=160 default (Microsoft: "lowest value for 90% of cases")
- Soft timeout (4s → play filler) + Hard timeout (15s → abort)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import json_repair
import tiktoken

from app.observability.metrics import (
    observe_intent_latency_ms,
    observe_llm_latency_ms,
    record_json_repair,
    record_llm_fallback,
)

logger = logging.getLogger(__name__)

# tiktoken encoder for context management
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken (Microsoft pattern)."""
    return len(_encoder.encode(text))


def truncate_messages(messages: list[dict], budget: int = 6000) -> list[dict]:
    """Truncate conversation history to fit token budget.

    Microsoft pattern: keep system prompt + last N messages that fit.
    Always preserves the system message (index 0) and last user message.
    """
    if not messages:
        return messages

    # System prompt always kept
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    system_tokens = sum(count_tokens(m.get("content", "")) for m in system_msgs)
    remaining_budget = budget - system_tokens

    # Keep messages from the end until budget exhausted
    kept = []
    for msg in reversed(other_msgs):
        msg_tokens = count_tokens(msg.get("content", ""))
        if remaining_budget - msg_tokens < 0 and len(kept) >= 2:
            break
        kept.append(msg)
        remaining_budget -= msg_tokens

    kept.reverse()
    return system_msgs + kept


def repair_json_response(text: str, tenant_id: str = "default") -> str:
    """Apply json-repair to LLM output. Microsoft uses this on every response.

    Handles: missing quotes, trailing commas, unclosed braces, etc.
    Zero-cost insurance against LLM hallucination.
    """
    try:
        repaired = json_repair.repair_json(text, return_objects=False)
        if repaired != text:
            logger.info("json-repair fixed LLM output")
            record_json_repair(tenant_id)
        return repaired
    except Exception:
        return text


class LLMService:
    """Dual-LLM with production safeguards.

    Usage:
        llm = LLMService(mistral_key, groq_key)
        response = await llm.chat(messages, tools, max_tokens=160)
    """

    def __init__(self, mistral_api_key: str, groq_api_key: str, context_budget: int = 6000):
        self._mistral_key = mistral_api_key
        self._groq_key = groq_api_key
        self._context_budget = context_budget
        self._mistral_client = None
        self._groq_client = None

    async def _ensure_clients(self):
        if self._mistral_client is None and self._mistral_key:
            from mistralai import Mistral
            self._mistral_client = Mistral(api_key=self._mistral_key)
        if self._groq_client is None and self._groq_key:
            from groq import AsyncGroq
            self._groq_client = AsyncGroq(api_key=self._groq_key)

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 160,
        model: str = "",  # Set via settings.llm_fallback_model
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """Send messages to LLM with tool-calling support.

        1. Truncate history to context budget (tiktoken)
        2. Try primary LLM (Mistral)
        3. Fallback to fast LLM (Groq) on failure
        4. Apply json-repair on tool call arguments

        Returns dict with: content, tool_calls, model, tokens, latency_ms
        """
        await self._ensure_clients()

        # Step 1: tiktoken truncation
        messages = truncate_messages(messages, self._context_budget)

        start = time.monotonic()

        # Step 2: Try primary (Mistral)
        try:
            result = await self._call_mistral(messages, tools, max_tokens, model)
            result["fallback"] = False
        except Exception as e:
            logger.warning("Mistral failed (%s), falling back to Groq", e)
            # Step 3: Fallback to Groq
            try:
                record_llm_fallback(tenant_id=tenant_id, provider="groq")
                result = await self._call_groq(messages, tools, max_tokens)
                result["fallback"] = True
            except Exception as e2:
                logger.error("Both LLMs failed: Mistral=%s, Groq=%s", e, e2)
                return {
                    "content": "",
                    "tool_calls": [],
                    "model": "none",
                    "tokens": 0,
                    "latency_ms": (time.monotonic() - start) * 1000,
                    "fallback": True,
                    "error": str(e2),
                }

        result["latency_ms"] = (time.monotonic() - start) * 1000
        observe_llm_latency_ms(result["latency_ms"])

        # Step 4: json-repair on tool call arguments
        for tc in result.get("tool_calls", []):
            if isinstance(tc.get("arguments"), str):
                tc["arguments"] = repair_json_response(tc["arguments"], tenant_id=tenant_id)

        return result

    async def _call_mistral(self, messages, tools, max_tokens, model) -> dict:
        response = await self._mistral_client.chat.complete_async(
            model=model,
            messages=messages,
            tools=tools or [],
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in (choice.message.tool_calls or [])
            ],
            "model": model,
            "tokens": response.usage.total_tokens if response.usage else 0,
        }

    async def _call_groq(self, messages, tools, max_tokens) -> dict:
        kwargs = {
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        response = await self._groq_client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in (choice.message.tool_calls or [])
            ],
            "model": "llama-3.1-8b-instant",
            "tokens": response.usage.total_tokens if response.usage else 0,
        }

    async def chat_fast(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 80,
        tenant_id: str = "default",
    ) -> dict:
        """Use Groq directly for fast decisions (IVR navigation, classification)."""
        await self._ensure_clients()
        messages = truncate_messages(messages, 4000)
        start = time.monotonic()
        try:
            result = await self._call_groq(messages, tools, max_tokens)
        except Exception as e:
            logger.error("Groq fast call failed: %s", e)
            return {"content": "", "tool_calls": [], "model": "none", "tokens": 0, "latency_ms": 0, "error": str(e)}
        result["latency_ms"] = (time.monotonic() - start) * 1000
        observe_intent_latency_ms(result["latency_ms"])
        result["fallback"] = False
        return result

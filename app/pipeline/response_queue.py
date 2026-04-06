"""Response queue — Dialogflow CX-inspired response architecture.

Implements:
1. Response queue model: queue responses during agent turn, flush on completion
2. Partial responses: send filler while backend works (reduces perceived latency)
3. Conditional responses: select response based on call state
4. Channel-specific responses: telephony vs text format
5. No-immediate-repeat: IBM watsonx pattern for response variation

Based on Google Dialogflow CX fulfillment docs + IBM watsonx dialog docs.
"""
from __future__ import annotations

import logging
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueuedResponse:
    """A response waiting to be sent."""
    text: str
    priority: int = 0  # lower = higher priority
    is_partial: bool = False  # partial response (sent before main)
    channel: str = "telephony"  # telephony, text, or default
    condition: str = ""  # optional condition key


class ResponseQueue:
    """Manages response ordering and deduplication.

    Dialogflow CX pattern: multiple fulfillments can queue responses per turn.
    Responses are ordered by priority and flushed when the turn completes.
    """

    def __init__(self):
        self._queue: deque[QueuedResponse] = deque()
        self._recent: list[str] = []  # last N responses for no-repeat
        self._recent_max = 5

    def enqueue(self, text: str, priority: int = 0, is_partial: bool = False, channel: str = "telephony") -> None:
        """Add a response to the queue."""
        if not text.strip():
            return
        self._queue.append(QueuedResponse(text=text, priority=priority, is_partial=is_partial, channel=channel))

    def enqueue_partial(self, text: str) -> None:
        """Add a partial response — sent immediately to reduce perceived latency.

        Dialogflow CX: 'Return partial response' flushes queue before webhook completes.
        Use for fillers like 'Un instant...' while RAG/LLM processes.
        """
        self.enqueue(text, priority=-10, is_partial=True)

    def flush(self, channel: str = "telephony") -> list[str]:
        """Flush and return all queued responses for a channel, ordered by priority."""
        items = sorted(self._queue, key=lambda r: r.priority)
        self._queue.clear()

        results = []
        for item in items:
            if item.channel not in (channel, "default"):
                continue
            # IBM watsonx no-immediate-repeat: skip if same as recent
            if item.text in self._recent and not item.is_partial:
                continue
            results.append(item.text)

        # Track recent for no-repeat
        for text in results:
            self._recent.append(text)
            if len(self._recent) > self._recent_max:
                self._recent.pop(0)

        return results

    def flush_partials(self) -> list[str]:
        """Flush only partial responses (for immediate sending during processing)."""
        partials = [r for r in self._queue if r.is_partial]
        self._queue = deque(r for r in self._queue if not r.is_partial)
        return [r.text for r in partials]

    def clear(self) -> None:
        self._queue.clear()


# ── Filler responses for partial response pattern ──
FILLERS_PROCESSING = [
    "Un instant...",
    "Je verifie...",
    "Attendez, je regarde...",
    "Laissez-moi verifier ca...",
]

FILLERS_HOLD_RETURN = [
    "Oui je suis toujours la.",
    "Je suis la, merci d'avoir patiente.",
    "Merci pour votre patience.",
]


def pick_filler(category: str = "processing", exclude: str = "") -> str:
    """Pick a filler response, avoiding the last one used."""
    pool = FILLERS_PROCESSING if category == "processing" else FILLERS_HOLD_RETURN
    available = [f for f in pool if f != exclude]
    return random.choice(available) if available else pool[0]


# ── Conditional response selection (IBM watsonx pattern) ──
def select_conditional_response(
    responses: dict[str, list[str]],
    condition: str,
    last_used: str = "",
) -> str:
    """Select response based on condition, with variation and no-repeat.

    IBM watsonx pattern: condition-driven selection + sequential/random variation.

    Args:
        responses: dict mapping condition keys to response lists
        condition: which condition to match
        last_used: last response text (for no-repeat)
    """
    variants = responses.get(condition, responses.get("default", ["..."]))
    available = [v for v in variants if v != last_used]
    return random.choice(available) if available else variants[0]

"""Tool call loop detector — prevents pathological tool retry spirals.

Production failure mode: LLM calls a tool, tool returns an error or ambiguous
result, and the LLM retries with the same parameters indefinitely. This costs
money (API calls), time (call duration), and damages UX (agent stuck).

LiveKit has a per-turn ceiling (max_tool_steps=8) but no cross-turn detection.
This module adds sliding-window fingerprint matching across the whole call.

Design decisions (sourced from research):
- Fingerprint: hash(tool_name + canonical_json(args)) — args only, no result.
  Including results would hide true loops (same input, same error = loop).
- Threshold: 3 identical fingerprints in 60s sliding window.
  2 is legitimate retry; 3 is pathological.
- Recovery: LoopDetectedError → forces graceful end_call with tool_loop_aborted outcome.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass, field


class LoopDetectedError(RuntimeError):
    """Raised when a tool call fingerprint repeats beyond the abort threshold."""

    def __init__(self, tool_name: str, fingerprint: str, count: int):
        super().__init__(f"tool_loop: {tool_name} fp={fingerprint} count={count}")
        self.tool_name = tool_name
        self.fingerprint = fingerprint
        self.count = count


@dataclass
class LoopDetector:
    """Detects repeated (tool_name, args) fingerprints within a sliding window.

    Attributes:
        window_seconds: Sliding window for fingerprint matching (default 60s).
        threshold_warn: Count at which to log a warning (default 2).
        threshold_abort: Count at which to raise LoopDetectedError (default 3).
    """

    window_seconds: float = 60.0
    threshold_warn: int = 2
    threshold_abort: int = 3
    _history: deque = field(default_factory=lambda: deque(maxlen=128))

    @staticmethod
    def fingerprint(tool_name: str, args: dict | None) -> str:
        """Generate a stable short fingerprint for (tool, args) pair."""
        payload = json.dumps(args or {}, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha1(f"{tool_name}|{payload}".encode()).hexdigest()[:16]

    def record(self, tool_name: str, args: dict | None = None) -> tuple[int, str]:
        """Record a tool call and return (current_count_in_window, fingerprint).

        Prunes entries older than window_seconds before counting.
        """
        now = time.monotonic()
        fp = self.fingerprint(tool_name, args)
        cutoff = now - self.window_seconds
        while self._history and self._history[0][1] < cutoff:
            self._history.popleft()
        self._history.append((fp, now))
        count = sum(1 for f, _ in self._history if f == fp)
        return count, fp

    def reset(self) -> None:
        """Clear history (call at start of new session)."""
        self._history.clear()

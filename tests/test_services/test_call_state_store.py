"""Tests for CallStateStore checkpoint and restore."""
import asyncio
import json

from app.models.session_state import CallSessionState
from app.services.call_state_store import CallStateStore


class FakeRedis:
    """Minimal fake Redis for testing (no real server needed)."""

    def __init__(self):
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self._data[key] = value
        return True

    async def scan_keys(self, pattern: str, count: int = 100) -> list[str]:
        import fnmatch
        return [k for k in self._data if fnmatch.fnmatch(k, pattern)][:count]

    async def delete(self, key: str) -> bool:
        self._data.pop(key, None)
        return True

    async def incr(self, key: str, ttl: int | None = None) -> int | None:
        val = int(self._data.get(key, "0")) + 1
        self._data[key] = str(val)
        return val


def test_initialize_and_get():
    redis = FakeRedis()
    store = CallStateStore(redis)

    asyncio.run(store.initialize("call-1", "tenant-1", "MGEN"))
    state = asyncio.run(store.get("call-1"))

    assert state is not None
    assert state["call_id"] == "call-1"
    assert state["phase"] == "dialing"
    assert state["ivr_path"] == []
    assert state["extracted"] == {}


def test_checkpoint_updates_fields():
    redis = FakeRedis()
    store = CallStateStore(redis)

    asyncio.run(store.initialize("call-2", "tenant-2", "Harmonie"))
    asyncio.run(store.checkpoint(
        "call-2",
        phase="ivr",
        extracted={"status": "pending"},
        ivr_path=["1", "3"],
        last_tool_name="press_digit",
        event="checkpoint_test",
    ))

    state = asyncio.run(store.get("call-2"))
    assert state["phase"] == "ivr"
    assert state["extracted"] == {"status": "pending"}
    assert state["ivr_path"] == ["1", "3"]
    assert state["last_tool_name"] == "press_digit"
    assert any(e["event"] == "checkpoint_test" for e in state["events"])


def test_checkpoint_preserves_unchanged_fields():
    redis = FakeRedis()
    store = CallStateStore(redis)

    asyncio.run(store.initialize("call-3", "tenant-3", "MGEN"))
    asyncio.run(store.checkpoint("call-3", phase="conversation"))
    asyncio.run(store.checkpoint("call-3", llm_timeouts=2))

    state = asyncio.run(store.get("call-3"))
    assert state["phase"] == "conversation"
    assert state["llm_timeouts"] == 2


def test_from_checkpoint_restores_session_state():
    redis = FakeRedis()
    store = CallStateStore(redis)

    asyncio.run(store.initialize("call-4", "tenant-4", "MGEN"))
    asyncio.run(store.checkpoint(
        "call-4",
        phase="ivr",
        extracted={"status": "pending"},
        ivr_path=["1", "3"],
        ivr_transcript=["tapez 1", "DTMF 3: remboursements"],
        pending_prefixes=["Merci, je reprends."],
        llm_timeouts=1,
        handoff_depth=1,
        durable_write_failures=2,
    ))

    checkpoint = asyncio.run(store.get("call-4"))
    restored = CallSessionState.from_checkpoint(
        checkpoint,
        call_id="call-4",
        tenant_id="tenant-4",
        mutuelle="MGEN",
    )

    assert restored.phase == "ivr"
    assert restored.ivr_path == ["1", "3"]
    assert restored.pending_prefixes == ["Merci, je reprends."]
    assert restored.llm_timeouts == 1
    assert restored.handoff_depth == 1
    assert restored.durable_write_failures == 2
    assert restored.extracted_data == {"status": "pending"}


def test_list_active_filters_completed():
    redis = FakeRedis()
    store = CallStateStore(redis)

    asyncio.run(store.initialize("optician-alpha-001", "alpha", "MGEN"))
    asyncio.run(store.initialize("optician-alpha-002", "alpha", "Harmonie"))
    asyncio.run(store.finalize("optician-alpha-002", "completed", {}))

    active = asyncio.run(store.list_active("alpha"))
    assert len(active) == 1
    assert active[0]["call_id"] == "optician-alpha-001"

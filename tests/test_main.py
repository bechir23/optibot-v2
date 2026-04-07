import asyncio
from types import SimpleNamespace

from app import main


class _FakeSession:
    def __init__(self):
        self.greet_calls = 0
        self.kwargs = []

    async def generate_reply(self, **kwargs):
        self.greet_calls += 1
        self.kwargs.append(kwargs)


def test_greet_when_participant_ready(monkeypatch):
    class FakeCtx:
        room = SimpleNamespace(name="room-1")

        async def wait_for_participant(self):
            return SimpleNamespace(identity="caller")

    session = _FakeSession()
    monkeypatch.setattr(main.settings, "participant_join_timeout_sec", 1.0)

    result = asyncio.run(
        main._greet_when_participant_ready(
            FakeCtx(),
            session,
            label="test",
            instructions="Bonjour",
        )
    )

    assert result is True
    assert session.greet_calls == 1
    assert session.kwargs[0]["instructions"] == "Bonjour"
    assert session.kwargs[0]["tool_choice"] == "none"


def test_greet_when_participant_ready_times_out(monkeypatch):
    class FakeCtx:
        room = SimpleNamespace(name="room-2")

        async def wait_for_participant(self):
            await asyncio.sleep(0.2)

    session = _FakeSession()
    monkeypatch.setattr(main.settings, "participant_join_timeout_sec", 0.01)

    result = asyncio.run(
        main._greet_when_participant_ready(
            FakeCtx(),
            session,
            label="test",
            instructions="Bonjour",
        )
    )

    assert result is False
    assert session.greet_calls == 0

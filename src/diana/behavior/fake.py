"""Test doubles for behavior I/O (no network)."""

from __future__ import annotations

from datetime import UTC, datetime


class FakeTelegramActuator:
    """Records ordered Telegram I/O calls; returns synthetic message ids."""

    def __init__(self, *, start_message_id: int = 1) -> None:
        self.calls: list[dict] = []
        self._next_id = start_message_id

    async def read_business_message(
        self,
        chat_id: int,
        message_id: int | None,
        *,
        business_connection_id: str,
    ) -> None:
        self.calls.append(
            {
                "op": "read_business_message",
                "chat_id": chat_id,
                "message_id": message_id,
                "business_connection_id": business_connection_id,
            }
        )

    async def send_chat_action(
        self,
        chat_id: int,
        action: str,
        *,
        business_connection_id: str,
    ) -> None:
        self.calls.append(
            {
                "op": "send_chat_action",
                "chat_id": chat_id,
                "action": action,
                "business_connection_id": business_connection_id,
            }
        )

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        business_connection_id: str,
    ) -> int:
        mid = self._next_id
        self._next_id += 1
        self.calls.append(
            {
                "op": "send_message",
                "chat_id": chat_id,
                "text": text,
                "business_connection_id": business_connection_id,
                "message_id": mid,
            }
        )
        return mid

    def send_count(self) -> int:
        return sum(1 for c in self.calls if c["op"] == "send_message")


class ImmediateClock:
    """Clock whose sleep is a no-op (or optional recorder)."""

    def __init__(self, *, now: datetime | None = None) -> None:
        self._now = now or datetime.now(UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class FixedDelayPolicy:
    """Deterministic delays for non-flaky unit tests."""

    def __init__(self, *, initial: float = 0.0, typing: float = 0.0) -> None:
        self._initial = initial
        self._typing = typing

    def initial_delay_seconds(self) -> float:
        return self._initial

    def typing_duration_seconds(self, text: str) -> float:
        _ = text
        return self._typing


__all__ = [
    "FakeTelegramActuator",
    "FixedDelayPolicy",
    "ImmediateClock",
]

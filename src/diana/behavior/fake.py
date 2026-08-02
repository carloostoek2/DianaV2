"""Test doubles for behavior I/O (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from diana.behavior.ports import TransientSendError


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
        parse_mode: str | None = None,
    ) -> int:
        mid = self._next_id
        self._next_id += 1
        self.calls.append(
            {
                "op": "send_message",
                "chat_id": chat_id,
                "text": text,
                "business_connection_id": business_connection_id,
                "parse_mode": parse_mode,
                "message_id": mid,
            }
        )
        return mid

    def send_count(self) -> int:
        return sum(1 for c in self.calls if c["op"] == "send_message")


class FlakySendActuator(FakeTelegramActuator):
    """Fails first N send_message with TransientSendError, then succeeds."""

    def __init__(
        self,
        *,
        fail_times: int = 1,
        start_message_id: int = 1,
        always_fail: bool = False,
    ) -> None:
        super().__init__(start_message_id=start_message_id)
        self._fail_times = fail_times
        self._always_fail = always_fail
        self._failures_so_far = 0
        self.send_attempts = 0

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        business_connection_id: str,
        parse_mode: str | None = None,
    ) -> int:
        self.send_attempts += 1
        if self._always_fail or self._failures_so_far < self._fail_times:
            self._failures_so_far += 1
            self.calls.append(
                {
                    "op": "send_message_failed",
                    "chat_id": chat_id,
                    "text": text,
                    "business_connection_id": business_connection_id,
                    "parse_mode": parse_mode,
                    "error": "transient",
                }
            )
            raise TransientSendError("transient send failure")
        return await super().send_message(
            chat_id, text, business_connection_id=business_connection_id
        )


class AlwaysLiveTurnStatusReader:
    """Returns a live turn status for unit tests (I.4 gate passes)."""

    def __init__(self, status: str = "pending_approval") -> None:
        self._status = status

    async def get_status(self, turn_id: UUID) -> str | None:
        _ = turn_id
        return self._status


class SequenceTurnStatusReader:
    """Returns successive statuses for race-oriented tests (no wall clock)."""

    def __init__(self, statuses: list[str | None]) -> None:
        self._statuses = list(statuses)
        self._idx = 0

    async def get_status(self, turn_id: UUID) -> str | None:
        _ = turn_id
        if self._idx >= len(self._statuses):
            return self._statuses[-1] if self._statuses else None
        status = self._statuses[self._idx]
        self._idx += 1
        return status


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

    def __init__(
        self,
        *,
        initial: float = 0.0,
        typing: float = 0.0,
        pre_read: float = 0.0,
        post_read: float = 0.0,
        inter_gap: float = 0.0,
    ) -> None:
        self._initial = initial
        self._typing = typing
        self._pre_read = pre_read
        self._post_read = post_read
        self._inter_gap = inter_gap

    def initial_delay_seconds(self, mode: str = "supervised") -> float:
        _ = mode
        return self._initial

    def typing_duration_seconds(self, text: str) -> float:
        _ = text
        return self._typing

    def pre_read_delay_seconds(self) -> float:
        return self._pre_read

    def post_read_delay_seconds(self) -> float:
        return self._post_read

    def inter_message_gap_seconds(self) -> float:
        return self._inter_gap


__all__ = [
    "AlwaysLiveTurnStatusReader",
    "FakeTelegramActuator",
    "FixedDelayPolicy",
    "FlakySendActuator",
    "ImmediateClock",
    "SequenceTurnStatusReader",
]

"""I/O ports for the behavior engine (no LLM, no cognitive decision modules).

English ↔ Anexo I (docstring map only):
- mode="supervised"      ↔ modo: "supervisado"
- mode="autonomous"      ↔ modo: "autonomo"
- mode="fake_delivery"   ↔ modo: "fake_delivery"
- DeliveryResult.success ↔ ok
- Pre-send TurnStatusReader ↔ I.4 last-mile supersede abort
- Bounded TransientSendError retries ↔ I.4 / REQ-NFR-04
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from diana.application.ports import DeliveryContext, DeliveryMode, DeliveryResult


class TransientSendError(Exception):
    """Transient channel/API failure eligible for bounded retry (I.4)."""


# Progress stages the owner sees while a supervised delivery is in flight.
# "sent" is not reported here: the caller maps the DeliveryResult itself.
ProgressKind = Literal["reading", "typing"]

DeliveryProgressCallback = Callable[[ProgressKind], Awaitable[None]]


@runtime_checkable
class TelegramActuatorPort(Protocol):
    """Telegram I/O for Business messages. Implementations must not decide content."""

    async def read_business_message(
        self,
        chat_id: int,
        message_id: int | None,
        *,
        business_connection_id: str,
    ) -> None: ...

    async def send_chat_action(
        self,
        chat_id: int,
        action: str,
        *,
        business_connection_id: str,
    ) -> None: ...

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        business_connection_id: str,
        parse_mode: str | None = None,
    ) -> int: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


@runtime_checkable
class DelayPolicy(Protocol):
    def initial_delay_seconds(self, mode: DeliveryMode = "supervised") -> float: ...

    def typing_duration_seconds(self, text: str) -> float: ...

    def pre_read_delay_seconds(self) -> float: ...

    def post_read_delay_seconds(self) -> float: ...

    def inter_message_gap_seconds(self) -> float: ...


@runtime_checkable
class TurnStatusReader(Protocol):
    """Read current turn status without cognitive imports (I.4 pre-send gate)."""

    async def get_status(self, turn_id: UUID) -> str | None:
        """Return current turn status string, or None if missing."""
        ...


__all__ = [
    "Clock",
    "DelayPolicy",
    "DeliveryContext",
    "DeliveryMode",
    "DeliveryProgressCallback",
    "DeliveryResult",
    "ProgressKind",
    "TelegramActuatorPort",
    "TransientSendError",
    "TurnStatusReader",
]

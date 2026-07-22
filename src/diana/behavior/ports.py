"""I/O ports for the behavior engine (no LLM, no cognitive decision modules)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DeliveryContext(BaseModel):
    """Context required to act a message toward a VIP chat."""

    model_config = ConfigDict(extra="forbid")

    chat_id: int
    business_connection_id: str
    vip_id: UUID | None = None
    mode: Literal["supervised"] = "supervised"
    telegram_message_id: int | None = None


class DeliveryResult(BaseModel):
    """Outcome of a deliver attempt."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    message_ids: list[int] = Field(default_factory=list)
    actual_delay_seconds: float = 0.0
    typing_duration_seconds: float = 0.0
    error: str | None = None
    cancelled: bool = False

    def to_trace_dict(self) -> dict:
        return self.model_dump(mode="json")


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
    ) -> int: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


@runtime_checkable
class DelayPolicy(Protocol):
    def initial_delay_seconds(self) -> float: ...

    def typing_duration_seconds(self, text: str) -> float: ...


__all__ = [
    "Clock",
    "DelayPolicy",
    "DeliveryContext",
    "DeliveryResult",
    "TelegramActuatorPort",
]

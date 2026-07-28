"""Pure unit tests for multi-segment owner history pairing."""

from __future__ import annotations

import pytest

from diana.application.owner_history import (
    append_owner_delivery_history,
    build_owner_history_pairs,
)
from diana.application.ports import DeliveryResult
from diana.application.memory import InMemoryMessageHistoryWriter


def test_pairs_aligned_texts_and_ids() -> None:
    result = DeliveryResult(
        success=True,
        message_ids=[10, 11, 12],
        texts=["a", "b", "c"],
    )
    assert build_owner_history_pairs(result, "fallback") == [
        ("a", 10),
        ("b", 11),
        ("c", 12),
    ]


def test_pairs_empty_ids_single_fallback_mid_none() -> None:
    result = DeliveryResult(success=True, message_ids=[], texts=[])
    assert build_owner_history_pairs(result, "full draft") == [
        ("full draft", None)
    ]


def test_pairs_mismatch_first_fallback_rest_empty() -> None:
    result = DeliveryResult(success=True, message_ids=[1, 2, 3], texts=[])
    assert build_owner_history_pairs(result, "full") == [
        ("full", 1),
        ("", 2),
        ("", 3),
    ]


def test_pairs_mismatch_partial_segs() -> None:
    result = DeliveryResult(
        success=True,
        message_ids=[1, 2, 3],
        texts=["only-first"],
    )
    assert build_owner_history_pairs(result, "fallback") == [
        ("only-first", 1),
        ("", 2),
        ("", 3),
    ]


@pytest.mark.asyncio
async def test_append_writes_all_pairs() -> None:
    history = InMemoryMessageHistoryWriter()
    result = DeliveryResult(
        success=True,
        message_ids=[10, 11],
        texts=["x", "y"],
    )
    await append_owner_delivery_history(
        history,
        42,
        result=result,
        fallback_text="fb",
    )
    rows = await history.get_recent(42)
    assert [(r["text"], r["telegram_message_id"]) for r in rows] == [
        ("x", 10),
        ("y", 11),
    ]


@pytest.mark.asyncio
async def test_append_continues_after_row_failure() -> None:
    """One failed append must not block remaining id linkages."""

    class FlakyHistory:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int | None]] = []
            self._n = 0

        async def append(
            self,
            chat_id: int,
            *,
            role: str,
            text: str,
            telegram_message_id: int | None = None,
            timestamp=None,
        ) -> None:
            self._n += 1
            self.calls.append((text, telegram_message_id))
            if self._n == 1:
                raise RuntimeError("db blip")

        async def get_recent(self, chat_id: int, *, limit: int = 20) -> list[dict]:
            return []

    hist = FlakyHistory()
    result = DeliveryResult(
        success=True,
        message_ids=[1, 2, 3],
        texts=["a", "b", "c"],
    )
    await append_owner_delivery_history(
        hist,  # type: ignore[arg-type]
        7,
        result=result,
        fallback_text="fb",
    )
    assert hist.calls == [("a", 1), ("b", 2), ("c", 3)]

"""OutcomeReactionJob — C3 reaction/silence backstop (Fila 4, SPEC §4/C3).

The immediate orchestrator hook classifies a VIP follow-up the moment it
arrives. This periodic job covers the REST of the reaction window:

- an outcome row whose delivery anchor is older than the window AND has no
  VIP follow-up → ``silence``;
- a follow-up that never went through the hook (e.g. the process was down, or
  the follow-up never entered the pipeline) → classify text-only (H2 lexicon).

Application-only wrapper (AGENTS.md: jobs delegate to application services —
the ``OutcomeLogService`` owns the writes and the trust events).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from diana.application.outcome_log_service import OutcomeLogService

logger = logging.getLogger("diana.jobs")

__all__ = ["OutcomeReactionJob", "first_vip_followup_text", "run_outcome_reaction_cycle"]


def first_vip_followup_text(
    history_rows: list[dict],
    *,
    after: datetime,
    window_seconds: int,
) -> str | None:
    """Earliest VIP message after ``after`` within ``window_seconds``.

    ``history_rows`` is ``message_history.get_recent`` output (newest first).
    Returns the text of the FIRST (oldest within the window) VIP message, or
    None when the VIP stayed silent.
    """
    window_end = after + timedelta(seconds=max(0, window_seconds))
    candidates: list[tuple[datetime, str]] = []
    for row in history_rows:
        if not isinstance(row, dict):
            continue
        if row.get("role") != "vip":
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        ts = row.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        if ts <= after or ts > window_end:
            continue
        candidates.append((ts, text))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


async def run_outcome_reaction_cycle(
    *,
    outcome: OutcomeLogService,
    history: Any,
    window_hours: int,
    limit: int = 200,
) -> dict[str, Any]:
    """One-shot: close pending reaction windows (classify or silence).

    Never raises out (per-item try/except; failures counted). Returns a small
    report for the job log.
    """
    try:
        pending = await outcome.list_signal_pending(
            window_hours=window_hours, limit=limit
        )
    except Exception:
        logger.exception("outcome_reaction_scan_failed")
        return {"processed": 0, "silence": 0, "reactions": 0, "errors": 1}

    window_seconds = outcome.reaction_window_seconds()
    report: dict[str, int] = {"processed": 0, "silence": 0, "reactions": 0, "errors": 0}
    for item in pending:
        try:
            turn_id = item["turn_id"]
            chat_id = item["chat_id"]
            anchor = item.get("anchor") or datetime.now(UTC)
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=UTC)
            recent = await history.get_recent(chat_id, limit=50)
            follow = first_vip_followup_text(
                recent, after=anchor, window_seconds=window_seconds
            )
            if follow is None:
                await outcome.record_reaction(turn_id, vip_signal="silence")
                report["silence"] += 1
            else:
                signal = outcome.classify_reaction(follow, None)
                await outcome.record_reaction(turn_id, vip_signal=signal)
                report["reactions"] += 1
            report["processed"] += 1
        except Exception:
            logger.exception(
                "outcome_reaction_item_failed", extra={"item": str(item.get("turn_id"))}
            )
            report["errors"] += 1

    logger.info(
        "outcome_reaction_cycle_complete",
        extra={"window_hours": window_hours, "report": report},
    )
    return report


class OutcomeReactionJob:
    """Periodically close C3 reaction windows (pattern CalibrationJob)."""

    def __init__(
        self,
        outcome: OutcomeLogService,
        history: Any,
        *,
        window_hours: int = 6,
        interval_seconds: int = 3600,
        limit: int = 200,
    ) -> None:
        self._outcome = outcome
        self._history = history
        self._window_hours = max(1, int(window_hours))
        self._interval = int(interval_seconds)
        self._limit = int(limit)
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        logger.info(
            "outcome_reaction_job_started",
            extra={"interval_seconds": self._interval, "window_hours": self._window_hours},
        )
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    run_outcome_reaction_cycle(
                        outcome=self._outcome,
                        history=self._history,
                        window_hours=self._window_hours,
                        limit=self._limit,
                    ),
                    timeout=self._interval,
                )
                logger.info(
                    "outcome_reaction_job_tick",
                    extra={"result": result, "duration_ms": int((time.monotonic() - t0) * 1000)},
                )
            except TimeoutError:
                logger.warning("outcome_reaction_cycle_timeout")
            except Exception:
                logger.exception("outcome_reaction_cycle_error")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                break
            except TimeoutError:
                continue
        logger.info("outcome_reaction_job_stopped")

    async def stop(self) -> None:
        self._stop_event.set()
        logger.debug("outcome_reaction_job_stop_signalled")

"""ProfileSynthesisService — LLM resynthesis of the VIP profile (Fase 1, shadow).

Application service (AGENTS.md §2.1) that turns the Fase 1 inputs into a
versioned ``vip_profile`` write:

- The prompt is THREE explicit, non-mixed blocks: ``current_profile`` (the
  persisted record), ``new_episodic_facts`` (visible facts since the last
  synthesis, A9) and ``feedback_signals`` (owner corrections since the last
  synthesis, A8/EA-04). The LLM answers with a forced-JSON
  :class:`SynthesisOutput` via ``generate_structured``.
- **Confidence gating lives HERE, not in the prompt** (A6): the service reads
  ``output.confidence`` and branches BEFORE writing. High (>= ``confidence_min``)
  overwrites stable_traits/recent_trend/sensitivities, bumps ``version`` and
  snapshots the PRIOR profile into ``vip_profile_history``. Low or ``None``
  (fail-safe) writes ONLY ``recent_trend`` — stable_traits/sensitivities stay
  intact, no version bump, no snapshot. BOTH branches advance
  ``last_synthesized_at`` so the volume trigger never re-processes the same
  old facts in a low-confidence loop (A6).
- Decay (spec 1.3) lives ONLY inside the prompt (age in days + explicit
  lower/remove instructions); the service only revalidates each sensitivity
  ``weight`` to [0,1] and drops out-of-range items (schema defense, A10).
- A failing LLM/schema call fails LOUD (no write, ``last_synthesized_at``
  intact) — the JOB catches and treats it as ``failed``; ``synthesize`` itself
  does not swallow exceptions. Nothing propagates past the job boundary.

This is the LLM-synthesized profile (Fase 1), DISTINTO de ``profiles`` (tabla
vector, ``repositories/memories.py``) y de ``/vip_profile`` (comando legacy
admin). The profile is shadow-only: nothing in generation reads it.

Purity: imports only stdlib + pydantic + ``application.ports`` +
``application.memory_backfill_service`` (LLMStructuredPort); no aiogram, no
infrastructure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from diana.application.memory_backfill_service import LLMStructuredPort
from diana.application.memory_extraction_service import MemoryFactsWriter
from diana.application.ports import VipProfileRecord
from diana.cognitive.models import SynthesisTrigger

logger = logging.getLogger("diana.application")

__all__ = [
    "ProfileSynthesisService",
    "SensitivityItem",
    "SynthesisCorrectionsSource",
    "SynthesisOutput",
    "SynthesisProfileStore",
    "SynthesisReport",
]


class SensitivityItem(BaseModel):
    """One sensitivity entry with a revalidated [0,1] weight (A10)."""

    model_config = ConfigDict(extra="forbid")

    trait: str
    weight: float  # no range at the schema level; the service revalidates [0,1]
    evidence_count: int = 0


class SynthesisOutput(BaseModel):
    """Structured LLM response for one profile synthesis."""

    model_config = ConfigDict(extra="forbid")

    stable_traits: dict[str, Any]
    recent_trend: dict[str, Any]
    sensitivities: list[SensitivityItem] = Field(default_factory=list)
    changes_summary: str = ""
    # None/absent → treated as LOW (A6, fail-safe).
    confidence: float | None = None


class SynthesisProfileStore(Protocol):
    """Profile store for the synthesis service (structural typing)."""

    async def get_by_vip(self, vip_id: UUID) -> VipProfileRecord | None: ...

    async def get_or_create(self, vip_id: UUID) -> VipProfileRecord: ...

    async def save_synthesis_result(
        self,
        vip_id: UUID,
        *,
        previous: VipProfileRecord | None,
        next: VipProfileRecord,
        changes_summary: str | None,
    ) -> VipProfileRecord: ...


class SynthesisCorrectionsSource(Protocol):
    """Owner-corrections source for feedback_signals (structural typing)."""

    async def list_corrections_by_vip_since(
        self, vip_id: UUID, *, since: datetime | None, limit: int = 50
    ) -> list[dict]: ...


@dataclass(frozen=True, slots=True)
class SynthesisReport:
    """Outcome of one synthesis run.

    ``status``: ``ok`` | ``low_confidence`` | ``failed``. ``failed`` is emitted
    by the JOB (which catches the loud exception); ``synthesize`` itself raises
    on LLM/schema failure (no write).
    """

    status: str
    vip_id: UUID
    trigger: SynthesisTrigger | None = None
    version: int = 0
    confidence: float | None = None
    error: str | None = None


class ProfileSynthesisService:
    """Resynthesizes one VIP profile with confidence gating in the service."""

    def __init__(
        self,
        *,
        llm: LLMStructuredPort,
        profile_store: SynthesisProfileStore,
        memories: MemoryFactsWriter,
        corrections: SynthesisCorrectionsSource,
        confidence_min: float = 0.6,
    ) -> None:
        self._llm = llm
        self._profile_store = profile_store
        self._memories = memories
        self._corrections = corrections
        self._confidence_min = max(0.0, min(1.0, float(confidence_min)))

    def apply_overrides(self, config: dict) -> None:
        """Manual ``confidence_min`` override (system_config key ``profile_synthesis``).

        The ONLY override point — never auto-calibrated. Missing keys are
        ignored; invalid values are rejected without crashing; the value is
        clamped to [0,1].
        """
        if not isinstance(config, dict):
            return
        try:
            raw = config.get("confidence_min")
            if raw is not None:
                value = float(raw)
                self._confidence_min = max(0.0, min(1.0, value))
        except (TypeError, ValueError):
            pass

    def _build_prompt(
        self,
        current: VipProfileRecord,
        facts: list[dict],
        signals: list[dict],
    ) -> list[dict]:
        """Three explicit, non-mixed blocks; decay instructions live here (A10)."""
        age_days = None
        if current.last_synthesized_at is not None:
            age_days = max(
                0, (datetime.now(UTC) - current.last_synthesized_at).days
            )
        system = (
            "You update a VIP's synthesized profile from the three data blocks. "
            "Rules:\n"
            "- NEVER invent facts: every trait must be grounded in "
            "new_episodic_facts or feedback_signals.\n"
            "- DECAY: the current profile was last synthesized "
            + (f"{age_days} days ago." if age_days is not None else "at an unknown time.")
            + " Lower the weight of anything not reinforced by new_episodic_facts; "
            "REMOVE an item from sensitivities (NEVER from stable_traits) when its "
            "weight falls below 0.3.\n"
            "- feedback_signals mix tone/personality feedback with one-off content "
            "corrections; keep only what reflects the VIP's stable self.\n"
            "- confidence: ALWAYS return it as a number between 0 and 1 "
            "(required — it gates how much of the current profile is "
            "overwritten). Keep it LOW when there are few facts or "
            "contradictory signals.\n"
            "- changes_summary: one short sentence describing what changed."
        )
        user = json.dumps(
            {
                "current_profile": current.model_dump(
                    mode="json", exclude={"vip_id"}
                ),
                "new_episodic_facts": facts,
                "feedback_signals": signals,
            },
            ensure_ascii=False,
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    async def synthesize(
        self, vip_id: UUID, trigger: SynthesisTrigger
    ) -> SynthesisReport:
        """Run one synthesis cycle for ``vip_id``.

        Reads the inputs, calls the LLM (fails LOUD on LLM/schema error — no
        write, ``last_synthesized_at`` intact so the next trigger retries),
        applies the confidence gate and persists via ``save_synthesis_result``.
        Does NOT catch exceptions; the JOB turns any raise into a ``failed``
        report and always calls ``release``.
        """
        persisted = await self._profile_store.get_by_vip(vip_id)
        was_persisted = persisted is not None
        current = await self._profile_store.get_or_create(vip_id)
        # S2: capture ``now`` BEFORE the reads. The new ``last_synthesized_at``
        # is derived from this timestamp, so a fact created while the LLM
        # window runs never falls into the gap between the read and the write
        # (created_at >= new last_synthesized_at would otherwise skip it on the
        # next run too).
        now = datetime.now(UTC)

        facts = await self._memories.list_by_vip_since(
            vip_id, since=current.last_synthesized_at
        )
        signals = await self._corrections.list_corrections_by_vip_since(
            vip_id, since=current.last_synthesized_at
        )

        output = cast(
            SynthesisOutput,
            await self._llm.generate_structured(
                self._build_prompt(current, facts, signals), SynthesisOutput
            ),
        )

        # Schema defense (A10): drop out-of-range sensitivity weights.
        cleaned = [s for s in output.sensitivities if 0.0 <= s.weight <= 1.0]
        if len(cleaned) != len(output.sensitivities):
            logger.warning(
                "profile_synthesis_dropped_sensitivities",
                extra={
                    "vip_id": str(vip_id),
                    "kept": len(cleaned),
                    "dropped": len(output.sensitivities) - len(cleaned),
                },
            )

        conf = (
            0.0
            if output.confidence is None
            else max(0.0, min(1.0, float(output.confidence)))
        )

        if conf >= self._confidence_min:
            nxt = VipProfileRecord(
                vip_id=vip_id,
                stable_traits=output.stable_traits,
                recent_trend=output.recent_trend,
                sensitivities=[s.model_dump() for s in cleaned],
                version=current.version + 1,
                last_synthesized_at=now,
                synthesis_trigger=trigger,
            )
            await self._profile_store.save_synthesis_result(
                vip_id,
                previous=(current if was_persisted else None),
                next=nxt,
                # S7: never coerce "" to None — the audit trail (1.4) must stay
                # populated even when the LLM sends no summary.
                changes_summary=(
                    output.changes_summary
                    or "profile resynthesized (no detail provided)"
                ),
            )
            return SynthesisReport(
                status="ok",
                vip_id=vip_id,
                trigger=trigger,
                version=nxt.version,
                confidence=conf,
            )

        # Low / absent confidence (fail-safe): only recent_trend, no bump,
        # no snapshot. last_synthesized_at still advances (A6).
        nxt = VipProfileRecord(
            vip_id=vip_id,
            stable_traits=current.stable_traits,
            recent_trend=output.recent_trend,
            sensitivities=current.sensitivities,
            version=current.version,
            last_synthesized_at=now,
            synthesis_trigger=trigger,
        )
        await self._profile_store.save_synthesis_result(
            vip_id, previous=None, next=nxt, changes_summary=None
        )
        logger.info(
            "profile_synthesis_low_confidence",
            extra={
                "vip_id": str(vip_id),
                "confidence": conf,
                "trigger": trigger,
            },
        )
        return SynthesisReport(
            status="low_confidence",
            vip_id=vip_id,
            trigger=trigger,
            version=nxt.version,
            confidence=conf,
        )

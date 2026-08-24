"""OutcomeLogService — the Fila 4 learning circle (SPEC-AUTONOMIA-CALIBRACION §4–§7).

Closes the shadow-mode loop with the missing question: "¿habría acertado?".

- C1 (coincidence): re-decide a finished turn with the shadow Decider
  (autonomy ON) → shadow_verdict; compare with what the owner actually did →
  acierto / desacuerdo / conservadora (pure table in ``coincidence.py``).
- C2 (quality): score the shadow draft and the actually-sent text with the
  H1 heuristic (``text_quality_heuristics``) → draft_score / sent_score /
  quality_delta (None when the scorer is not wired or no text).
- C3 (reaction): the VIP's follow-up signal (positive/neutral/negative/silence)
  lands on the outcome row when the reaction window closes.

Writes are STRICTLY post-turn (never inside the pipeline): the shadow half is
written by the orchestrator's post-turn hook; the owner half when the owner
resolves; the reaction half by the reaction job. Flag-gated — with the Fila 4
flag off, the service is a no-op (byte-identical pre-Fila-4 behavior).

``list_comparativas`` is the Fase A on-the-fly reader (existing tables, no new
schema); when the persistent store is wired (Fase B, migration 030) the same
rows come from ``turn_outcome_log``.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from diana.application.coincidence import CoincidenceLabel, label as label_turn
from diana.application.ports import (
    OutcomeSourceReader,
    TurnOutcomeLogRecord,
    TurnOutcomeLogStore,
    VipStore,
)
from diana.cognitive.models import (
    Comprehension,
    Decision,
    EvaluationProfile,
)

logger = logging.getLogger("diana.application")

__all__ = [
    "CoincidenceRow",
    "OutcomeLogService",
    "derive_owner_outcome",
    "shadow_verdict_from_decision",
]

# Default reaction window (hours) — C3 "ventana de reacción del VIP".
DEFAULT_REACTION_WINDOW_HOURS = 6

# Text scorer protocol: H1 (text_quality_heuristics.score) with a VIP name.
class TextScorer(Protocol):
    def __call__(self, text: str, *, vip_name: str | None = None) -> float: ...


@dataclass(frozen=True)
class CoincidenceRow:
    """One finished turn compared: shadow verdict vs. real owner outcome."""

    turn_id: UUID
    vip_id: UUID | None
    chat_id: int
    created_at: datetime | None
    status: str
    draft: str | None = None
    corrected_text: str | None = None
    shadow_verdict: str | None = None
    shadow_reason: str | None = None
    owner_outcome: str | None = None
    label: CoincidenceLabel | None = None
    quality_delta: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def shadow_verdict_from_decision(decision: Decision) -> tuple[str, str]:
    """Map a shadow re-decision to the §7 verdict vocab ``(verdict, reason)``.

    ``send`` (would have sent alone) · ``blocked`` (thresholds missed, approve
    fallback) · ``escalate`` (safety/risk/frustration) · ``doctrine`` (gray
    zone pending).
    """
    action = decision.action
    reason = decision.reason or "unknown"
    if action == "send":
        return "send", reason
    if action == "escalate":
        return "escalate", reason
    if action == "consult_doctrine":
        return "doctrine", reason
    return "blocked", reason


def compute_blocked_dims(
    evaluation: EvaluationProfile, mins: tuple[float, float, float]
) -> list[str]:
    """Dimensions below the autonomous mins when the verdict is ``blocked``."""
    safety_min, doctrine_min, naturalness_min = mins
    out: list[str] = []
    if evaluation.safety < safety_min:
        out.append("safety")
    if evaluation.doctrine < doctrine_min:
        out.append("doctrine")
    if evaluation.naturalness < naturalness_min:
        out.append("naturalness")
    return out


def derive_owner_outcome(
    status: str | None,
    approval_status: str | None,
    has_staging_correction: bool,
) -> str | None:
    """Deterministic owner-outcome derivation from persisted turn state.

    - ``escalated`` status → escalated (the owner discarded/escalated).
    - ``delivered`` + correction persisted or approval marked ``corrected``
      → corrected; otherwise → approved_as_is.
    - Any other (open/superseded/failed) → None (no outcome yet).
    """
    if status == "escalated":
        return "escalated"
    if status == "delivered":
        if has_staging_correction or approval_status == "corrected":
            return "corrected"
        return "approved_as_is"
    return None


class OutcomeLogService:
    """Fila 4 learning circle: shadow → owner → reaction → trust adjustment.

    ``decider`` is the SHADOW Decider (autonomy switch ON — same matrix, never
    decides live). ``store`` / ``source`` are the persistent log (Fase B) and
    the on-the-fly source (Fase A); ``scorer`` is the H1 quality heuristic
    (Fase B). With any of them None, the corresponding half is a no-op.
    """

    def __init__(
        self,
        *,
        decider: Any,
        store: TurnOutcomeLogStore | None = None,
        source: OutcomeSourceReader | None = None,
        scorer: TextScorer | None = None,
        vips: VipStore | None = None,
        trust_budget: Any | None = None,
        reaction_classifier: Any | None = None,
        enabled: bool = False,
        reaction_window_hours: int = DEFAULT_REACTION_WINDOW_HOURS,
    ) -> None:
        self._decider = decider
        self._store = store
        self._source = source
        self._scorer = scorer
        self._vips = vips
        self._trust_budget = trust_budget
        self._reaction_classifier = reaction_classifier
        self._enabled = bool(enabled)
        self._reaction_window = max(1, int(reaction_window_hours))

    # ------------------------------------------------------------------
    # Fase A — on-the-fly coincidence (existing tables, no new schema)
    # ------------------------------------------------------------------

    async def list_comparativas(
        self, window_days: int = 14, limit: int = 200
    ) -> list[CoincidenceRow]:
        """Compare finished VIP turns (newest first) using the shadow Decider."""
        if self._source is None:
            return []
        raw_rows = await self._source.list_finished_source_turns(
            window_days=window_days, limit=limit
        )
        return [self._build_comparativa(raw) for raw in raw_rows]

    async def coincidence_summary(
        self, window_days: int = 14, limit: int = 500
    ) -> dict[str, Any]:
        """Aggregates for the panel: counts, rate and the disagreement list."""
        rows = await self.list_comparativas(window_days=window_days, limit=limit)
        labels = [r.label for r in rows]
        counts = Counter(labels)
        n_labeled = sum(counts.values())
        aciertos = counts.get("acierto", 0)
        desacuerdos = counts.get("desacuerdo", 0)
        conservadora = counts.get("conservadora", 0)
        return {
            "n": len(rows),
            "n_labeled": n_labeled,
            "aciertos": aciertos,
            "desacuerdos": desacuerdos,
            "conservadora": conservadora,
            "rate": (
                aciertos / (aciertos + desacuerdos)
                if (aciertos + desacuerdos) > 0
                else None
            ),
            "desacuerdos_list": [r for r in rows if r.label == "desacuerdo"],
        }

    def _build_comparativa(self, raw: dict[str, Any]) -> CoincidenceRow:
        verdict: str | None = None
        reason: str | None = None
        blocked: list[str] = []
        eval_dict = raw.get("evaluation")
        comp_dict = raw.get("comprehension")
        if eval_dict and comp_dict:
            try:
                evaluation = EvaluationProfile.model_validate(eval_dict)
                comprehension = Comprehension.model_validate(comp_dict)
                decision = self._decider.decide(
                    evaluation,
                    comprehension,
                    retrieved=raw.get("retrieved") or {},
                )
                verdict, reason = shadow_verdict_from_decision(decision)
                if verdict == "blocked":
                    blocked = compute_blocked_dims(
                        evaluation, self._decider.autonomous_mins()
                    )
            except Exception:
                logger.warning(
                    "outcome_redecide_failed",
                    extra={"turn_id": str(raw.get("turn_id"))},
                )
        owner_outcome = derive_owner_outcome(
            raw.get("status"),
            raw.get("approval_status"),
            bool(raw.get("has_staging_correction")),
        )
        return CoincidenceRow(
            turn_id=raw["turn_id"],
            vip_id=raw.get("vip_id"),
            chat_id=raw.get("chat_id"),
            created_at=raw.get("created_at"),
            status=raw.get("status") or "",
            draft=raw.get("draft"),
            corrected_text=raw.get("corrected_text"),
            shadow_verdict=verdict,
            shadow_reason=reason,
            owner_outcome=owner_outcome,
            label=(
                label_turn(verdict, owner_outcome)
                if verdict is not None and owner_outcome is not None
                else None
            ),
            extra={"blocked_dims": blocked},
        )

    # ------------------------------------------------------------------
    # Fase B — persistent ledger writes (post-turn / owner / reaction)
    # ------------------------------------------------------------------

    def reaction_window_seconds(self) -> int:
        return self._reaction_window * 3600

    async def find_pending_signal_for_chat(
        self, chat_id: int, *, since: datetime
    ) -> TurnOutcomeLogRecord | None:
        """C3 immediate hook: last row for the chat still missing its signal."""
        if not self._enabled or self._store is None:
            return None
        return await self._store.find_pending_signal_for_chat(chat_id, since=since)

    def classify_reaction(
        self, text: str | None, comprehension: dict[str, Any] | None
    ) -> str:
        """C3 H2: classify a follow-up message (positive/neutral/negative)."""
        if self._reaction_classifier is None:
            return "neutral"
        return self._reaction_classifier(text, comprehension)

    async def record_shadow(
        self,
        turn_id: UUID,
        *,
        vip_id: UUID,
        trace: dict[str, Any] | None,
    ) -> TurnOutcomeLogRecord | None:
        """Post-turn shadow half: re-decide + score the draft, insert the row.

        Best-effort (never raises out); idempotent by ``turn_id``. No row when
        the trace lacks evaluation/comprehension (template cut, aborted).
        """
        if not self._enabled or self._store is None or trace is None:
            return None
        try:
            verdict, reason, blocked = self._redecide(trace)
            if verdict is None:
                return None
            draft = (trace.get("generated_text") or "").strip()
            draft_score = await self._score_draft(draft, vip_id)
            return await self._store.insert(
                TurnOutcomeLogRecord(
                    turn_id=turn_id,
                    vip_id=vip_id,
                    shadow_verdict=verdict,
                    shadow_reason=reason,
                    draft_score=draft_score,
                    blocked_dims=blocked,
                )
            )
        except Exception:
            logger.exception(
                "outcome_record_shadow_failed", extra={"turn_id": str(turn_id)}
            )
            return None

    async def record_owner_outcome(
        self,
        turn_id: UUID,
        *,
        owner_outcome: str,
        sent_text: str | None,
        vip_id: UUID | None,
    ) -> TurnOutcomeLogRecord | None:
        """Owner-resolution half: sent score + delta + trust label event.

        ``escalated`` carries no sent text → sent_score/quality_delta stay
        None. Fires the trust-budget label event (acierto/desacuerdo/
        conservadora) once per outcome.
        """
        if not self._enabled or self._store is None:
            return None
        try:
            sent_score: float | None = None
            delta: float | None = None
            if sent_text is not None and owner_outcome in (
                "approved_as_is",
                "corrected",
            ):
                sent_score = await self._score_text(sent_text, vip_id)
                current = await self._store.get_by_turn_id(turn_id)
                if current is not None and sent_score is not None:
                    delta = round(sent_score - (current.draft_score or 0.0), 6)
            updated = await self._store.update_outcome(
                turn_id,
                owner_outcome=owner_outcome,
                sent_score=sent_score,
                quality_delta=delta,
            )
            if updated is not None and self._trust_budget is not None:
                coincidence = label_turn(updated.shadow_verdict, owner_outcome)
                if coincidence is not None:
                    await self._trust_budget.record_outcome(
                        turn_id, event="label", value=coincidence
                    )
            return updated
        except Exception:
            logger.exception(
                "outcome_record_owner_failed", extra={"turn_id": str(turn_id)}
            )
            return None

    async def list_signal_pending(
        self, *, window_hours: int, limit: int = 200
    ) -> list[dict]:
        """C3 job: outcome rows without a reaction whose window already closed."""
        if not self._enabled or self._store is None:
            return []
        return await self._store.list_signal_pending(
            window_hours=window_hours, limit=limit
        )

    async def count_safety_escalations_since(
        self, since: datetime
    ) -> int:
        """C6 gate: escalations caused by the safety dimension in the window."""
        if self._store is None:
            return 0
        return await self._store.count_safety_escalations_since(since=since)

    async def list_outcome_rows_since(
        self, since: datetime, limit: int = 500
    ) -> list[TurnOutcomeLogRecord]:
        """Recent outcome-log rows (Fase B panels; empty when the log is off)."""
        if self._store is None:
            return []
        return await self._store.list_recent(since=since, limit=limit)

    async def record_reaction(
        self,
        turn_id: UUID,
        *,
        vip_signal: str,
    ) -> TurnOutcomeLogRecord | None:
        """Reaction half (C3): persist the VIP signal + trust signal event.

        Idempotent by signal value: the trust event fires only when the
        persisted signal CHANGES (or was None), so the immediate orchestrator
        hook and the periodic backstop job can never double-apply a signal.
        """
        if not self._enabled or self._store is None:
            return None
        try:
            current = await self._store.get_by_turn_id(turn_id)
            if current is None:
                return None
            if current.vip_signal == vip_signal:
                return current  # already recorded — no-op (no double event)
            updated = await self._store.update_signal(turn_id, vip_signal=vip_signal)
            if updated is not None and self._trust_budget is not None:
                await self._trust_budget.record_outcome(
                    turn_id, event="signal", value=vip_signal
                )
            return updated
        except Exception:
            logger.exception(
                "outcome_record_reaction_failed", extra={"turn_id": str(turn_id)}
            )
            return None

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _redecide(self, trace: dict[str, Any]) -> tuple[str | None, str | None, list[str]]:
        eval_dict = trace.get("evaluation")
        comp_dict = trace.get("comprehension")
        if not eval_dict or not comp_dict:
            return None, None, []
        evaluation = EvaluationProfile.model_validate(eval_dict)
        comprehension = Comprehension.model_validate(comp_dict)
        decision = self._decider.decide(
            evaluation, comprehension, retrieved=trace.get("retrieved") or {}
        )
        verdict, reason = shadow_verdict_from_decision(decision)
        blocked = (
            compute_blocked_dims(evaluation, self._decider.autonomous_mins())
            if verdict == "blocked"
            else []
        )
        return verdict, reason, blocked

    async def _vip_name(self, vip_id: UUID | None) -> str | None:
        if vip_id is None or self._vips is None:
            return None
        try:
            vip = await self._vips.get_by_id(vip_id)
            return vip.display_name if vip is not None else None
        except Exception:
            return None

    async def _score_text(self, text: str, vip_id: UUID | None) -> float | None:
        if self._scorer is None or not (text or "").strip():
            return None
        name = await self._vip_name(vip_id)
        return float(self._scorer(text, vip_name=name))

    async def _score_draft(self, draft: str, vip_id: UUID) -> float | None:
        return await self._score_text(draft, vip_id)

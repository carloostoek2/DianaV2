"""GrayZoneService — doctrinal query lifecycle and VIP freeze management.

Flows (AGENTS §4.5 — rule → live policy → force regen → approval):
1. create_query → insert gray_zone_query (open) + freeze VIP
2. persist_live_policy → active policies row (NO staging on happy path)
3. mark_awaiting_send → status awaiting_send (freeze retained)
4. close_awaiting_send → resolved + optional unfreeze (after successful send)
5. discard_and_close → close without policy + unfreeze (escalate/parachute)
6. Legacy resolve_with_doctrine / confirm_and_apply — superseded for owner
   happy path; may remain for migration/tests only
7. expire_old_queries — marks open queries past timeout as expired
   (does NOT expire awaiting_send)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from diana.application.ports import VipStore
from diana.cognitive.policy_distiller import PolicyDistiller
from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo
from diana.infrastructure.db.repositories.policies import PoliciesRepo, policy_to_dict
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo

logger = logging.getLogger("diana.application")


class _Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


def _trigger_from_rule(rule_text: str, question: str) -> str:
    """Build trigger_description: first line if multi-line else truncated question."""
    lines = [ln.strip() for ln in rule_text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines[0][:500]
    q = (question or "").strip()
    if q:
        return q[:500]
    return (rule_text or "").strip()[:500] or "doctrine_rule"


class GrayZoneService:
    """Manages the gray zone query lifecycle and VIP freezing.

    Injectable deps: GrayZoneQueryRepo, VipStore, StagingCandidateRepo,
    PolicyDistiller, PoliciesRepo (live persist), optional embedder.
    """

    def __init__(
        self,
        *,
        query_repo: GrayZoneQueryRepo,
        vip_store: VipStore,
        staging_repo: StagingCandidateRepo,
        distiller: PolicyDistiller,
        default_timeout_hours: int = 24,
        policies_repo: PoliciesRepo | None = None,
        embedder: _Embedder | None = None,
    ) -> None:
        self._queries = query_repo
        self._vips = vip_store
        self._staging = staging_repo
        self._distiller = distiller
        self._default_timeout = default_timeout_hours
        self._policies = policies_repo
        self._embedder = embedder

    async def create_query(
        self,
        vip_id: UUID | None,
        turn_id: UUID,
        question: str,
        draft: str,
        *,
        freeze_duration_hours: int | None = None,
        chat_id: int | None = None,
        business_connection_id: str | None = None,
        proposed_rule: str | None = None,
        proposed_reply: str | None = None,
        proposal_source: str | None = None,
    ) -> object:
        """Create an open gray zone query; freeze the VIP when present.

        VIP is frozen FIRST so that no window exists where the query is
        inserted but the VIP is unfrozen. If freeze_vip raises, no insert
        occurs. For atencion (``vip_id is None``) there is no VIP to freeze —
        the atencion chat freeze is the open/awaiting_send query row itself.

        FEATURE_GRAY_ZONE_PROPOSAL_ENABLED: the optional system RULE proposal
        (GrayZoneProposalService) is persisted on the query for audit + dp:
        callback recovery. It never enters memories/examples/policies.
        """
        duration = freeze_duration_hours or self._default_timeout
        frozen_until = datetime.now(UTC) + timedelta(hours=duration)

        if vip_id is not None:
            await self._vips.freeze_vip(vip_id, frozen_until)

        row = await self._queries.insert(
            vip_id=vip_id,
            turn_id=turn_id,
            question=question,
            draft=draft,
            freeze_until=frozen_until,
            chat_id=chat_id,
            business_connection_id=business_connection_id,
            proposed_rule=proposed_rule,
            proposed_reply=proposed_reply,
            proposal_source=proposal_source,
        )

        logger.info(
            "gray_zone_query_created",
            extra={
                "query_id": str(row.id),
                "vip_id": str(vip_id) if vip_id is not None else None,
                "chat_id": chat_id,
                "turn_id": str(turn_id),
                "frozen_until": frozen_until.isoformat(),
            },
        )
        return row

    async def persist_live_policy(
        self,
        query_id: UUID,
        rule_text: str,
        *,
        vip_id: UUID | None = None,
        scope: str = "all",
    ) -> object:
        """Insert an active policy for an open gray-zone query (no staging).

        Does NOT close the query or unfreeze. Returns the Policy ORM row.
        """
        if self._policies is None:
            raise RuntimeError("policies_repo is required for persist_live_policy")
        if query_id is None:
            raise ValueError("query_id is required to persist live policy")
        rule = (rule_text or "").strip()
        if not rule:
            raise ValueError("rule_text is required to persist live policy")

        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status != "open":
            raise ValueError(
                f"GrayZoneQuery {query_id} status is {query.status!r}, "
                f"expected 'open'"
            )

        # Idempotent retry: reuse active policy already written for this query.
        if hasattr(self._policies, "find_active_by_source_query_id"):
            existing = await self._policies.find_active_by_source_query_id(query_id)
            if existing is not None:
                logger.info(
                    "gray_zone_live_policy_reused",
                    extra={
                        "query_id": str(query_id),
                        "policy_id": str(existing.id),
                    },
                )
                return existing

        trigger = _trigger_from_rule(rule, getattr(query, "question", "") or "")
        embedding: list[float] | None = None
        if self._embedder is not None:
            try:
                embedding = await self._embedder.embed(f"{trigger}\n{rule}")
            except Exception:
                logger.exception(
                    "gray_zone_live_policy_embed_failed",
                    extra={"query_id": str(query_id)},
                )

        policy = await self._policies.insert(
            trigger_description=trigger,
            rule=rule,
            scope=scope if scope in {"vip", "all"} else ("vip" if vip_id else "all"),
            is_active=True,
            source_query_id=query_id,
            embedding=embedding,
            vip_id=vip_id,
        )
        logger.info(
            "gray_zone_live_policy_persisted",
            extra={
                "query_id": str(query_id),
                "policy_id": str(policy.id),
                "scope": scope,
                "vip_id": str(vip_id) if vip_id is not None else None,
            },
        )
        return policy

    async def deactivate_policy(self, policy_id: UUID) -> bool:
        """Deactivate a live policy (regen fail / fail-closed)."""
        if self._policies is None:
            raise RuntimeError("policies_repo is required to deactivate_policy")
        ok = await self._policies.deactivate(policy_id)
        logger.info(
            "gray_zone_policy_deactivated",
            extra={"policy_id": str(policy_id), "ok": ok},
        )
        return ok

    def policy_override_payload(self, policy: Any) -> dict[str, Any]:
        """Build Director knowledge_overrides entry from a live policy row."""
        if isinstance(policy, dict):
            return dict(policy)
        # Prefer ORM helper only when the row looks like a real Policy model.
        if hasattr(policy, "created_at") and hasattr(policy, "valid_until"):
            try:
                return policy_to_dict(policy)
            except Exception:
                pass
        return {
            "id": str(getattr(policy, "id", "") or ""),
            "trigger_description": getattr(policy, "trigger_description", "") or "",
            "rule": getattr(policy, "rule", "") or "",
            "scope": getattr(policy, "scope", "all") or "all",
            "is_active": bool(getattr(policy, "is_active", True)),
            "vip_id": (
                str(policy.vip_id) if getattr(policy, "vip_id", None) else None
            ),
            "source_query_id": (
                str(policy.source_query_id)
                if getattr(policy, "source_query_id", None)
                else None
            ),
        }
    async def mark_awaiting_send(self, query_id: UUID) -> None:
        """Move open query to awaiting_send. Does NOT unfreeze."""
        if query_id is None:
            raise ValueError("query_id is required to mark awaiting_send")
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status not in {"open", "awaiting_send"}:
            raise ValueError(
                f"GrayZoneQuery {query_id} status is {query.status!r}, "
                f"expected 'open' or 'awaiting_send'"
            )
        if query.status == "awaiting_send":
            return
        await self._queries.update_status(query_id, "awaiting_send")
        logger.info(
            "gray_zone_awaiting_send",
            extra={"query_id": str(query_id)},
        )

    async def close_awaiting_send(
        self, query_id: UUID, *, unfreeze: bool = False
    ) -> object:
        """Resolve an awaiting_send (or open) query; optionally unfreeze VIP."""
        if query_id is None:
            raise ValueError("query_id is required to close awaiting_send")
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status not in {"open", "awaiting_send"}:
            raise ValueError(
                f"GrayZoneQuery {query_id} status is {query.status!r}, "
                f"expected 'open' or 'awaiting_send'"
            )
        now = datetime.now(UTC)
        await self._queries.update_status(query_id, "resolved", resolved_at=now)
        if unfreeze and query.vip_id is not None:
            try:
                await self._vips.unfreeze_vip(query.vip_id)
            except ValueError:
                logger.warning(
                    "Failed to unfreeze VIP %s for awaiting_send close %s",
                    query.vip_id,
                    query_id,
                )
        logger.info(
            "gray_zone_awaiting_send_closed",
            extra={
                "query_id": str(query_id),
                "unfreeze": unfreeze,
                "vip_id": str(query.vip_id) if query.vip_id else None,
            },
        )
        return query

    async def resolve_with_doctrine(
        self,
        query_id: UUID,
        generalization: str,
        rule: str,
        *,
        vip_id: UUID | None = None,
    ) -> object:
        """Legacy: create StagingCandidate (type='policy'). Superseded for owner happy path."""
        if query_id is None:
            raise ValueError("query_id is required to resolve with doctrine")
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status != "open":
            raise ValueError(
                f"GrayZoneQuery {query_id} status is {query.status!r}, "
                f"expected 'open'"
            )

        payload = {
            "question": query.question,
            "draft": query.draft,
            "generalization": generalization,
            "rule": rule,
            "query_id": str(query_id),
            "vip_id": str(vip_id) if vip_id is not None else None,
            "scope": "vip" if vip_id is not None else "all",
        }
        candidate = await self._staging.insert("policy", payload, query.turn_id)

        logger.info(
            "gray_zone_resolved_with_doctrine",
            extra={
                "query_id": str(query_id),
                "candidate_id": str(candidate.id),
            },
        )
        return candidate

    async def confirm_and_apply(
        self,
        query_id: UUID,
        candidate_id: UUID,
    ) -> object:
        """Legacy: close query + unfreeze. Superseded for owner happy path."""
        if query_id is None:
            raise ValueError("query_id is required to confirm and apply")
        if candidate_id is None:
            raise ValueError("candidate_id is required to confirm and apply")
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status != "open":
            raise ValueError(
                f"GrayZoneQuery {query_id} status is {query.status!r}, "
                f"expected 'open'"
            )

        now = datetime.now(UTC)
        await self._queries.update_status(query_id, "resolved", resolved_at=now)

        if query.vip_id is not None:
            try:
                await self._vips.unfreeze_vip(query.vip_id)
            except ValueError:
                logger.warning(
                    "Failed to unfreeze VIP %s for resolved query %s",
                    query.vip_id,
                    query_id,
                )

        logger.info(
            "gray_zone_query_closed",
            extra={
                "query_id": str(query_id),
                "vip_id": str(query.vip_id),
            },
        )
        return query

    async def discard_and_close(self, query_id: UUID) -> object:
        """Close a gray zone query without a policy (owner escalate / parachute).

        Accepts ``open`` or ``awaiting_send``. Unfreezes the VIP.
        """
        if query_id is None:
            raise ValueError("query_id is required to discard and close")
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status not in {"open", "awaiting_send"}:
            raise ValueError(
                f"GrayZoneQuery {query_id} status is {query.status!r}, "
                f"expected 'open' or 'awaiting_send'"
            )

        now = datetime.now(UTC)
        await self._queries.update_status(query_id, "resolved", resolved_at=now)

        if query.vip_id is not None:
            try:
                await self._vips.unfreeze_vip(query.vip_id)
            except ValueError:
                logger.warning(
                    "Failed to unfreeze VIP %s for discarded query %s",
                    query.vip_id,
                    query_id,
                )

        logger.info(
            "gray_zone_query_discarded",
            extra={"query_id": str(query_id)},
        )
        return query

    async def get_open_query_by_turn_id(self, turn_id: UUID) -> object | None:
        """Look up an open query by turn ID (status=open only)."""
        return await self._queries.get_open_by_turn_id(turn_id)

    async def get_awaiting_send_by_turn_id(self, turn_id: UUID) -> object | None:
        """Look up an awaiting_send query by turn ID."""
        return await self._queries.get_awaiting_send_by_turn_id(turn_id)

    async def get_hold_query_by_turn_id(self, turn_id: UUID) -> object | None:
        """Open or awaiting_send query for a turn (doctrine hold)."""
        q = await self._queries.get_open_by_turn_id(turn_id)
        if q is not None:
            return q
        return await self._queries.get_awaiting_send_by_turn_id(turn_id)

    async def get_open_query_by_vip_id(self, vip_id: UUID) -> object | None:
        """Look up open|awaiting_send query by VIP id (freeze/reminder)."""
        return await self._queries.get_open_by_vip_id(vip_id)

    async def get_open_query_by_chat_id(self, chat_id: int) -> object | None:
        """Look up open|awaiting_send query by chat id (atencion freeze)."""
        return await self._queries.get_open_by_chat_id(chat_id)

    async def reopen_query(self, query_id: UUID) -> bool:
        """Re-open a closed or awaiting_send query so a later run can retry it."""
        if query_id is None:
            raise ValueError("query_id is required to reopen")
        row = await self._queries.get_by_id(query_id)
        if row is None:
            return False
        if row.status not in {"resolved", "expired", "awaiting_send"}:
            logger.info(
                "gray_zone_query_reopen_skipped",
                extra={"query_id": str(query_id), "status": row.status},
            )
            return False
        return await self._queries.update_status(query_id, "open")

    async def freeze_vip(self, vip_id: UUID, duration_hours: int | None = None) -> None:
        """Freeze a VIP for a given duration (or default timeout)."""
        if vip_id is None:
            raise ValueError("vip_id is required to freeze a VIP")
        duration = duration_hours or self._default_timeout
        frozen_until = datetime.now(UTC) + timedelta(hours=duration)
        await self._vips.freeze_vip(vip_id, frozen_until)
        logger.info(
            "vip_frozen",
            extra={
                "vip_id": str(vip_id),
                "frozen_until": frozen_until.isoformat(),
            },
        )

    async def unfreeze_vip(self, vip_id: UUID) -> None:
        """Unfreeze a VIP (clear frozen_until)."""
        if vip_id is None:
            raise ValueError("vip_id is required to unfreeze a VIP")
        await self._vips.unfreeze_vip(vip_id)
        logger.info("vip_unfrozen", extra={"vip_id": str(vip_id)})

    async def expire_old_queries(
        self,
        timeout_hours: int | None = None,
    ) -> list[object]:
        """Mark open queries older than timeout_hours as expired.

        Only status='open' rows are expired (awaiting_send is never expired here).
        Unfreezes VIPs for expired queries.
        """
        timeout = timeout_hours or self._default_timeout
        expired = await self._queries.expire_older_than(timeout)

        for row in expired:
            if row.vip_id is not None:
                try:
                    await self._vips.unfreeze_vip(row.vip_id)
                except ValueError:
                    logger.warning(
                        "Failed to unfreeze VIP %s for expired query %s",
                        row.vip_id,
                        row.id,
                    )
            logger.info(
                "gray_zone_query_expired",
                extra={
                    "query_id": str(row.id),
                    "vip_id": str(row.vip_id),
                    "action": "expired",
                },
            )

        return expired


__all__ = ["GrayZoneService"]

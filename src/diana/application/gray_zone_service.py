"""GrayZoneService — doctrinal query lifecycle and VIP freeze management.

Flows (from SPEC-FASE2 6.2):
1. create_query → insert gray_zone_query (open) + freeze VIP
2. resolve_with_doctrine → create StagingCandidate (type='policy') + does NOT close query
3. confirm_and_apply → close query (resolved) + unfreeze VIP
4. discard_and_close → close query without policy + unfreeze VIP
5. freeze_vip / unfreeze_vip — direct VIP freeze control
6. expire_old_queries — marks open queries past timeout as expired
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from diana.application.ports import VipStore
from diana.cognitive.policy_distiller import PolicyDistiller
from diana.infrastructure.db.repositories.gray_zone import GrayZoneQueryRepo
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo

logger = logging.getLogger("diana.application")


class GrayZoneService:
    """Manages the gray zone query lifecycle and VIP freezing.

    Injectable deps: GrayZoneQueryRepo (DB), VipStore (freeze VIPs),
    StagingCandidateRepo (create pending policy candidates),
    PolicyDistiller (structure doctrine text).
    """

    def __init__(
        self,
        *,
        query_repo: GrayZoneQueryRepo,
        vip_store: VipStore,
        staging_repo: StagingCandidateRepo,
        distiller: PolicyDistiller,
        default_timeout_hours: int = 24,
    ) -> None:
        self._queries = query_repo
        self._vips = vip_store
        self._staging = staging_repo
        self._distiller = distiller
        self._default_timeout = default_timeout_hours

    async def create_query(
        self,
        vip_id: UUID,
        turn_id: UUID,
        question: str,
        draft: str,
        *,
        freeze_duration_hours: int | None = None,
    ) -> object:
        """Create an open gray zone query and freeze the VIP.

        The VIP remains frozen until the query is resolved or expired.
        Returns the ORM GrayZoneQuery row.
        """
        duration = freeze_duration_hours or self._default_timeout
        frozen_until = datetime.now(UTC) + timedelta(hours=duration)

        row = await self._queries.insert(
            vip_id=vip_id,
            turn_id=turn_id,
            question=question,
            draft=draft,
            freeze_until=frozen_until,
        )
        await self._vips.freeze_vip(vip_id, frozen_until)

        logger.info(
            "gray_zone_query_created",
            extra={
                "query_id": str(row.id),
                "vip_id": str(vip_id),
                "turn_id": str(turn_id),
                "frozen_until": frozen_until.isoformat(),
            },
        )
        return row

    async def resolve_with_doctrine(
        self,
        query_id: UUID,
        generalization: str,
        rule: str,
    ) -> object:
        """Resolve a gray zone query with owner-provided doctrine.

        Creates a StagingCandidate (type='policy') with the distilled policy
        as payload. The candidate must be confirmed by the owner to become
        active (StagingService.promote_to_policy in Item 3).

        Does NOT close the query or unfreeze here — that happens on
        confirmation (Item 3). Returns the StagingCandidate row.
        """
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
        """Close a gray zone query and unfreeze VIP after policy confirmation.

        This is called AFTER StagingService.promote_to_policy succeeds (Item 3).
        Included here for completeness so the service owns the full lifecycle.
        Returns the updated GrayZoneQuery row.

        Raises:
            ValueError: If the query is not found or not in 'open' status.
        """
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
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} disappeared after update")

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
        """Close a gray zone query without a policy (owner said no).

        Unfreezes the VIP and marks the query as resolved with no policy.

        Raises:
            ValueError: If the query is not found or not in 'open' status.
        """
        query = await self._queries.get_by_id(query_id)
        if query is None:
            raise ValueError(f"GrayZoneQuery {query_id} not found")
        if query.status != "open":
            raise ValueError(
                f"GrayZoneQuery {query_id} status is {query.status!r}, "
                f"expected 'open'"
            )

        now = datetime.now(UTC)
        if query.vip_id is not None:
            try:
                await self._vips.unfreeze_vip(query.vip_id)
            except ValueError:
                logger.warning(
                    "Failed to unfreeze VIP %s for discarded query %s",
                    query.vip_id,
                    query_id,
                )

        await self._queries.update_status(query_id, "resolved", resolved_at=now)

        logger.info(
            "gray_zone_query_discarded",
            extra={"query_id": str(query_id)},
        )
        return await self._queries.get_by_id(query_id)

    async def freeze_vip(self, vip_id: UUID, duration_hours: int | None = None) -> None:
        """Freeze a VIP for a given duration (or default timeout)."""
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
        await self._vips.unfreeze_vip(vip_id)
        logger.info("vip_unfrozen", extra={"vip_id": str(vip_id)})

    async def expire_old_queries(
        self,
        timeout_hours: int | None = None,
    ) -> list[object]:
        """Mark open queries older than timeout_hours as expired.

        Returns the list of expired GrayZoneQuery rows.
        Unfreezes VIPs for expired queries.
        Returns an empty list if no queries are expired.
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
                    "action": "escalate",
                },
            )

        return expired


__all__ = ["GrayZoneService"]

"""StagingService — capture corrections and promote them to examples or policies.

Every new policy (gray zone or manual) must go through promote_to_policy().
Staging requires explicit owner confirmation — never auto-promote.
"""

from __future__ import annotations

import logging
from uuid import UUID

from diana.cognitive.models import Policy as PolicyDomain
from diana.infrastructure.db.repositories.examples import ExamplesRepo
from diana.infrastructure.db.repositories.policies import PoliciesRepo
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo

logger = logging.getLogger("diana.application")


class StagingService:
    """Captures corrections and promotes them to examples or policies.

    Injectable deps: StagingCandidateRepo, ExamplesRepo, PoliciesRepo.
    """

    def __init__(
        self,
        *,
        staging_repo: StagingCandidateRepo,
        examples_repo: ExamplesRepo,
        policies_repo: PoliciesRepo,
    ) -> None:
        self._staging = staging_repo
        self._examples = examples_repo
        self._policies = policies_repo

    async def save_correction(
        self,
        turn_id: UUID,
        original_draft: str,
        corrected_text: str,
        context: dict,
    ) -> object:
        """Save a correction as a pending staging candidate (type='example').

        The owner must later confirm promotion for this to become a live example.
        Returns the ORM StagingCandidate row (id, type, payload, status, turn_id).
        """
        payload = {
            "original_draft": original_draft,
            "corrected_text": corrected_text,
            "context": context,
        }
        row = await self._staging.insert("example", payload, turn_id)
        logger.info(
            "correction_saved",
            extra={
                "turn_id": str(turn_id),
                "candidate_id": str(row.id),
            },
        )
        return row

    async def promote_to_example(
        self,
        candidate_id: UUID,
    ) -> object:
        """Promote a staging candidate to a live example in the examples table.

        Returns the ORM Example row. Raises ValueError if candidate not found
        or not in 'pending' status.
        """
        candidate = await self._staging.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        if candidate.status != "pending":
            raise ValueError(
                f"StagingCandidate {candidate_id} status is {candidate.status!r}, "
                f"expected 'pending'"
            )

        payload = candidate.payload
        example = await self._examples.insert(
            turn_text=payload.get("context", {}).get("turn_text", ""),
            draft_text=payload.get("original_draft", ""),
            corrected_text=payload.get("corrected_text", ""),
            context=payload.get("context", {}),
            is_counter_example=False,
        )
        await self._staging.update_status(candidate_id, "promoted")
        logger.info(
            "example_promoted",
            extra={
                "candidate_id": str(candidate_id),
                "example_id": str(example.id),
            },
        )
        return example

    async def promote_to_policy(
        self,
        candidate_id: UUID,
        trigger: str,
        rule: str,
        scope: str = "all",
    ) -> PolicyDomain:
        """Promote a staging candidate to a live policy.

        Returns the domain Policy model (not ORM). Raises ValueError if
        candidate not found or not in 'pending' status.
        """
        candidate = await self._staging.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        if candidate.status != "pending":
            raise ValueError(
                f"StagingCandidate {candidate_id} status is {candidate.status!r}, "
                f"expected 'pending'"
            )

        orm_policy = await self._policies.insert(
            trigger_description=trigger,
            rule=rule,
            scope=scope,
            is_active=True,
            source_query_id=candidate.payload.get("query_id"),
        )
        await self._staging.update_status(candidate_id, "promoted")
        logger.info(
            "policy_promoted",
            extra={
                "candidate_id": str(candidate_id),
                "policy_id": str(orm_policy.id),
            },
        )
        return PolicyDomain(
            id=orm_policy.id,
            trigger_description=orm_policy.trigger_description,
            rule=orm_policy.rule,
            scope=orm_policy.scope,
            is_active=orm_policy.is_active,
            source_query_id=orm_policy.source_query_id,
            created_at=orm_policy.created_at,
        )

    async def discard(self, candidate_id: UUID) -> None:
        """Mark a staging candidate as discarded (no promotion).

        Raises ValueError if candidate not found.
        """
        updated = await self._staging.update_status(candidate_id, "discarded")
        if not updated:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        logger.info(
            "candidate_discarded",
            extra={"candidate_id": str(candidate_id)},
        )


__all__ = ["StagingService"]

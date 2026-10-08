"""StagingService — capture corrections and promote them to examples or policies.

Correction / UI ``/staging`` policies go through promote_to_policy().
Exception: gray-zone resolve happy path persists live via
GrayZoneService.persist_live_policy (no staging). Staging requires
explicit owner confirmation — never auto-promote from corrections.
"""

from __future__ import annotations

import logging
from uuid import UUID

from diana.application.policy_embedding import embed_policy_text, policy_embedding_text
from diana.cognitive.models import Policy as PolicyDomain
from diana.infrastructure.db.repositories.examples import ExamplesRepo
from diana.infrastructure.db.repositories.policies import PoliciesRepo
from diana.infrastructure.db.repositories.staging import StagingCandidateRepo

logger = logging.getLogger("diana.application")

# Reasons why a promoted row ends up carrying the zero vector. Same vocabulary
# as ProfilesRepo (`profile_embedding_zeros`) and PoliciesRepo
# (`policy_embedding_pending`): the row keeps the zeros, the reason stops being
# invisible (audit/FASE2-SABOTAJE.md §4, H-SB-1).
_NO_EMBEDDER = "no_embedder"
_EMPTY_TEXT = "empty_text"
_EMBEDDER_RETURNED_ZEROS = "embedder_returned_zeros"


class AtencionPromoteBlocked(ValueError):
    """Raised when an atencion correction is promoted to the VIP example bank.

    REQ-ATN-13 anti-contamination: atencion candidates are not promotable to
    VIP examples; the owner sees a distinct status instead of a generic "stale".
    """


class StagingService:
    """Captures corrections and promotes them to examples or policies.

    Injectable deps: StagingCandidateRepo, ExamplesRepo, PoliciesRepo,
    optional embedder (computes the retrieval fingerprint of promoted rows;
    same pattern as GrayZoneService.persist_live_policy).
    """

    def __init__(
        self,
        *,
        staging_repo: StagingCandidateRepo,
        examples_repo: ExamplesRepo,
        policies_repo: PoliciesRepo,
        sandbox: object | None = None,
        embedder: object | None = None,
    ) -> None:
        self._staging = staging_repo
        self._examples = examples_repo
        self._policies = policies_repo
        self._sandbox = sandbox
        self._embedder = embedder

    async def _embed(self, text: str) -> list[float] | None:
        """Compute the retrieval fingerprint for ``text``, or None.

        None when there is no embedder, no text, or the embed call fails. The
        row is still persisted (fail-open, mirroring GrayZoneService) and the
        examples repository turns that None into the zero vector, so the row
        ends up invisible to the similarity search. Persisting is deliberate;
        the *silence* is not: every None path logs its reason, with the same
        vocabulary as ProfilesRepo and PoliciesRepo (audit H-SB-1, 2026-10-08).

        Note: this removes the silence, not the zero — the row still carries
        the zero vector, which is what the daily watcher V1 alerts on.
        """
        if self._embedder is None:
            logger.warning(
                "staging_embed_zeros",
                extra={"reason": _NO_EMBEDDER, "text_len": len(text)},
            )
            return None
        if not text:
            # Legitimate: the candidate had nothing to fingerprint. Kept at
            # DEBUG, like the empty_text case in ProfilesRepo.
            logger.debug(
                "staging_embed_zeros",
                extra={"reason": _EMPTY_TEXT, "text_len": 0},
            )
            return None
        try:
            vec = await self._embedder.embed(text)
        except Exception:
            logger.exception(
                "staging_embed_failed",
                extra={"text_len": len(text)},
            )
            return None
        if not any(vec):
            # The August-2026 disguise: an all-zero vector is not "no
            # embedding", it is a row that looks valid and is invisible.
            logger.warning(
                "staging_embed_zeros",
                extra={"reason": _EMBEDDER_RETURNED_ZEROS, "text_len": len(text)},
            )
            return None
        return vec

    def _anchor_text(self, payload: dict) -> str:
        """Pick the text that best represents the example for retrieval."""
        context = payload.get("context") or {}
        return (
            context.get("turn_text")
            or payload.get("corrected_text")
            or payload.get("original_draft")
            or ""
        )

    async def save_correction(
        self,
        turn_id: UUID,
        original_draft: str,
        corrected_text: str,
        context: dict,
        *,
        chat_id: int | None = None,
        channel_type: str | None = None,
    ) -> object | None:
        """Save a correction as a pending staging candidate (type='example').

        The owner must later confirm promotion for this to become a live example.
        Returns the ORM StagingCandidate row (id, type, payload, status, turn_id).
        When sandbox is active for ``chat_id``, returns None without insert.
        ``channel_type`` is recorded so ``promote_to_example`` can block
        atencion-originated candidates from entering the VIP example bank
        (REQ-ATN-13 anti-contamination).
        """
        if (
            chat_id is not None
            and self._sandbox is not None
            and not self._sandbox.should_persist(chat_id)  # type: ignore[union-attr]
        ):
            logger.info(
                "correction_skipped_sandbox",
                extra={"turn_id": str(turn_id), "chat_id": chat_id},
            )
            return None
        payload = {
            "original_draft": original_draft,
            "corrected_text": corrected_text,
            "context": context,
            "channel_type": channel_type,
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
        if candidate.candidate_type != "example":
            raise ValueError(
                f"StagingCandidate {candidate_id} type is "
                f"{candidate.candidate_type!r}, expected 'example'"
            )

        # REQ-ATN-13 anti-contamination: atencion corrections must NEVER reach
        # the VIP example bank. Blocked BEFORE any insert so the candidate
        # stays pending (owner can still discard it).
        payload = candidate.payload
        if payload.get("channel_type") == "atencion":
            logger.info(
                "staging_atencion_promote_blocked",
                extra={"candidate_id": str(candidate_id)},
            )
            raise AtencionPromoteBlocked(
                "atencion candidates cannot be promoted to the VIP example bank"
            )

        example = await self._examples.insert(
            turn_text=payload.get("context", {}).get("turn_text", ""),
            draft_text=payload.get("original_draft", ""),
            corrected_text=payload.get("corrected_text", ""),
            context=payload.get("context", {}),
            is_counter_example=False,
            embedding=await self._embed(self._anchor_text(payload)),
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

    async def promote_to_counter_example(
        self,
        candidate_id: UUID,
        *,
        vip_id: UUID | None = None,
    ) -> object:
        """Promote a pending candidate to a counter-example in the bank."""
        candidate = await self._staging.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        if candidate.status != "pending":
            raise ValueError(
                f"StagingCandidate {candidate_id} status is {candidate.status!r}, "
                f"expected 'pending'"
            )
        if candidate.candidate_type != "example":
            raise ValueError(
                f"StagingCandidate {candidate_id} type is "
                f"{candidate.candidate_type!r}, expected 'example'"
            )

        # REQ-ATN-13 anti-contamination: atencion corrections must NEVER reach
        # the VIP example bank. Blocked BEFORE any insert so the candidate
        # stays pending (owner can still discard it).
        payload = candidate.payload
        if payload.get("channel_type") == "atencion":
            logger.info(
                "staging_atencion_promote_blocked",
                extra={"candidate_id": str(candidate_id)},
            )
            raise AtencionPromoteBlocked(
                "atencion candidates cannot be promoted to the VIP example bank"
            )

        example = await self._examples.insert(
            turn_text=payload.get("context", {}).get("turn_text", ""),
            draft_text=payload.get("original_draft", ""),
            corrected_text=payload.get("corrected_text", ""),
            context=payload.get("context", {}),
            is_counter_example=True,
            vip_id=vip_id,
            embedding=await self._embed(self._anchor_text(payload)),
        )
        await self._staging.update_status(candidate_id, "promoted")
        logger.info(
            "counter_example_promoted",
            extra={
                "candidate_id": str(candidate_id),
                "example_id": str(example.id),
                "vip_id": str(vip_id) if vip_id else None,
            },
        )
        return example

    async def insert_gold_example(
        self,
        *,
        turn_text: str,
        draft_text: str,
        corrected_text: str,
        context: dict,
        vip_id: UUID | None = None,
        channel_type: str | None = None,
        chat_id: int | None = None,
    ) -> object | None:
        """Insert a gold example after Destacar (no staging candidate required)."""
        if (
            chat_id is not None
            and self._sandbox is not None
            and not self._sandbox.should_persist(chat_id)  # type: ignore[union-attr]
        ):
            logger.info(
                "gold_example_skipped_sandbox",
                extra={"chat_id": chat_id},
            )
            return None
        if channel_type == "atencion":
            raise AtencionPromoteBlocked(
                "atencion candidates cannot be promoted to the VIP example bank"
            )
        return await self._examples.insert(
            turn_text=turn_text,
            draft_text=draft_text,
            corrected_text=corrected_text,
            context=context,
            is_counter_example=False,
            quality="gold",
            vip_id=vip_id,
            embedding=await self._embed(
                turn_text or corrected_text or draft_text
            ),
        )

    async def promote_to_policy(
        self,
        candidate_id: UUID,
        trigger: str,
        rule: str,
        scope: str = "all",
        vip_id: UUID | None = None,
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

        embedding = await embed_policy_text(
            self._embedder, policy_embedding_text(trigger, rule)
        )
        if embedding is None:
            logger.warning(
                "policy_embedding_pending",
                extra={
                    "candidate_id": str(candidate_id),
                    "source": "staging_promote",
                    "reason": "no_embedder" if self._embedder is None else "embed_failed",
                },
            )
        insert_kwargs: dict = {
            "trigger_description": trigger,
            "rule": rule,
            "scope": scope,
            "is_active": True,
            "source_query_id": candidate.payload.get("query_id"),
            "embedding": embedding,
        }
        if vip_id is not None:
            insert_kwargs["vip_id"] = vip_id
        orm_policy = await self._policies.insert(**insert_kwargs)
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

        Raises ValueError if candidate not found or not in 'pending' status.
        """
        candidate = await self._staging.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"StagingCandidate {candidate_id} not found")
        if candidate.status != "pending":
            raise ValueError(
                f"StagingCandidate {candidate_id} status is {candidate.status!r}, "
                f"expected 'pending'"
            )
        await self._staging.update_status(candidate_id, "discarded")
        logger.info(
            "candidate_discarded",
            extra={"candidate_id": str(candidate_id)},
        )

    async def list_pending_examples(self, limit: int = 10) -> list:
        """Return pending example candidates oldest-first (FIFO queue)."""
        return await self._staging.list_pending(
            candidate_type="example",
            limit=limit,
        )

    async def list_pending_policies(self, limit: int = 10) -> list:
        """Return pending policy candidates (gray zone doctrines) FIFO."""
        return await self._staging.list_pending(
            candidate_type="policy",
            limit=limit,
        )

    async def get_candidate(self, candidate_id: UUID) -> object | None:
        """Read one staging candidate (for type-routed promotion)."""
        return await self._staging.get_by_id(candidate_id)


__all__ = ["StagingService"]

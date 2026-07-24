"""SandboxService — fake profiles and trace isolation for F2 sandbox mode.

Sandbox mode allows testing the full pipeline with fake profiles,
isolated traces, and FakeDelivery. Full sandbox isolation (separate DB,
cloned profiles) is reserved for F3.
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger("diana.application")


class SandboxService:
    """Creates fake profiles and isolates traces for sandbox mode.

    Injected into composition root. When FEATURE_SANDBOX_ENABLED is True,
    this service creates sandbox profiles in the profiles table and marks
    traces with sandbox=True for auditability.
    """

    def __init__(
        self,
        *,
        profiles_repo: object | None = None,
        traces_repo: object | None = None,
    ) -> None:
        self._profiles = profiles_repo
        self._traces = traces_repo

    async def create_profile(
        self,
        channel_id: str,
        display_name: str,
    ) -> object | None:
        """Create a fake VIP profile for sandbox testing.

        Returns the ORM Profile row, or None if profiles_repo is not available.
        """
        if self._profiles is None:
            logger.debug("SandboxService: profiles_repo not configured, skipping")
            return None

        # In F2, profiles table exists but we insert a minimal row.
        # Full profile management is F3.
        row = await self._profiles.insert_sandbox(
            channel_id=channel_id,
            display_name=display_name,
        )
        logger.info(
            "sandbox_profile_created",
            extra={
                "channel_id": channel_id,
                "display_name": display_name,
            },
        )
        return row

    async def isolate_trace(self, turn_id: UUID) -> bool:
        """Mark a trace as sandbox for audit isolation.

        Returns True if the trace was marked, False if traces_repo is not available.
        """
        if self._traces is None:
            logger.debug("SandboxService: traces_repo not configured, skipping")
            return False

        # In F2, add a sandbox flag to the trace metadata.
        # traces table has a JSON 'metadata' column.
        await self._traces.set_metadata(turn_id, {"sandbox": True})
        logger.info(
            "sandbox_trace_isolated",
            extra={"turn_id": str(turn_id)},
        )
        return True


__all__ = ["SandboxService"]

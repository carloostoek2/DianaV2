"""Sandbox fixture profile inject — application-side KnowledgeAugmenter.

Cognitive only sees the Protocol; this module owns SandboxService coupling.
"""

from __future__ import annotations

from typing import Any

from diana.application.sandbox import SandboxService
from diana.cognitive.models import IncomingTurn


class SandboxKnowledgeAugmenter:
    """Force sandbox fixture facts/notes into ``knowledge.profile`` when active."""

    def __init__(self, sandbox: SandboxService) -> None:
        self._sandbox = sandbox

    async def augment_retrieved(
        self,
        turn: IncomingTurn,
        retrieved: dict[str, Any | None],
    ) -> dict[str, Any | None]:
        if not self._sandbox.is_active(turn.chat_id):
            return retrieved
        content = self._sandbox.get_profile_content(turn.chat_id)
        if content is None:
            return retrieved
        out = dict(retrieved)
        out["knowledge.profile"] = {
            "tipo": "sandbox_fixture",
            "content": content,
        }
        return out


__all__ = ["SandboxKnowledgeAugmenter"]

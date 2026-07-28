"""Sandbox fixture profile inject — application-side KnowledgeAugmenter.

Cognitive only sees the Protocol; this module owns SandboxService coupling.
"""

from __future__ import annotations

from typing import Any

from diana.application.sandbox import SandboxService
from diana.cognitive.models import IncomingTurn


class SandboxKnowledgeAugmenter:
    """Force sandbox fixture facts/notes/history into knowledge.* when active.

    Isolation scope: knowledge.profile AND knowledge.history. Without the
    history override, sandbox mode only fakes the profile while real chat
    history (from the tester's own VIP chat) keeps leaking into the prompt.
    """

    def __init__(self, sandbox: SandboxService) -> None:
        self._sandbox = sandbox

    async def augment_retrieved(
        self,
        turn: IncomingTurn,
        retrieved: dict[str, Any | None],
    ) -> dict[str, Any | None]:
        if not self._sandbox.is_active(turn.chat_id):
            return retrieved
        out = dict(retrieved)

        content = self._sandbox.get_profile_content(turn.chat_id)
        if content is not None:
            out["knowledge.profile"] = {
                "tipo": "sandbox_fixture",
                "content": content,
            }

        # Only override history if the caller actually requested it
        # (i.e. knowledge.history was already a key) — same "don't add
        # what wasn't planned" discipline as the rest of the pipeline.
        if "knowledge.history" in retrieved:
            history = self._sandbox.get_profile_history(turn.chat_id)
            out["knowledge.history"] = [
                {**row, "timestamp": ""} for row in (history or [])
            ]

        return out


__all__ = ["SandboxKnowledgeAugmenter"]

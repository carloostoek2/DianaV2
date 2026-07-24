"""PolicyDistiller — structures free text into a pure Policy domain model.

Lives in cognitive/ because it produces a cognitive-domain artifact (Policy).
No LLM dependency: the owner's generalization IS the structured input.
"""

from __future__ import annotations

from diana.cognitive.models import Policy

class PolicyDistiller:
    """Distills free-text doctrinal guidance into a structured Policy object.

    The owner provides three inputs:
    - question: the gray zone question (what the VIP asked)
    - answer: the owner's answer to the VIP
    - generalization: the owner's stated generalization/rule

    This is purely mechanical — the generalization provides the structure.
    """

    async def distill_from_text(
        self,
        question: str,
        answer: str,
        generalization: str,
    ) -> Policy:
        """Create a structured Policy from owner-provided text.

        Args:
            question: The original gray zone question (VIP's message).
            answer: The owner's crafted answer.
            generalization: The owner's stated rule (e.g. "Always offer 10% for 3+ units").

        Returns:
            A pure domain Policy with trigger_description derived from the
            generalization, and source_query_id left unset.

        Note:
            Returns an unsaved Policy object with id=None and created_at=None.
            The caller must persist it (e.g. via a repository or StagingCandidate).
        """
        # Mechanical extraction: generalization IS the rule; question provides trigger context.
        # If the owner provides a multi-line generalization, the first line is trigger,
        # remaining lines are rule. Otherwise use question as trigger and generalization as rule.
        lines = generalization.strip().split("\n", 1)
        trigger_candidate = lines[0].strip()
        rule_candidate = lines[1].strip() if len(lines) > 1 else generalization.strip()

        return Policy(
            trigger_description=trigger_candidate,
            rule=rule_candidate,
            scope="all",
            is_active=True,
            source_query_id=None,
        )


__all__ = ["PolicyDistiller"]

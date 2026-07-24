"""Unit tests for PolicyDistiller — mechanical generalization structuring.

PolicyDistiller is a pure cognitive module with no external dependencies.
Tests use the real class, no mocks needed.
"""

from __future__ import annotations

import pytest

from diana.cognitive.models import Policy
from diana.cognitive.policy_distiller import PolicyDistiller


@pytest.mark.asyncio
async def test_single_line_generalization_uses_as_rule() -> None:
    """Single-line generalization: trigger=generalization, rule=generalization."""
    distiller = PolicyDistiller()
    policy = await distiller.distill_from_text(
        question="VIP asks for discount on 3 units",
        answer="Sure, 10% off for 3+ units",
        generalization="Always offer 10% for 3+ units",
    )
    assert isinstance(policy, Policy)
    assert policy.trigger_description == "Always offer 10% for 3+ units"
    assert policy.rule == "Always offer 10% for 3+ units"
    assert policy.scope == "all"
    assert policy.is_active is True
    assert policy.source_query_id is None


@pytest.mark.asyncio
async def test_multi_line_generalization_splits_trigger_and_rule() -> None:
    """Multi-line generalization: first line is trigger, rest is rule."""
    distiller = PolicyDistiller()
    generalization = "VIP asks for bulk discount\nAlways offer 10% for 3+ units\nApply only to wholesale"
    policy = await distiller.distill_from_text(
        question="bulk discount?",
        answer="10% off",
        generalization=generalization,
    )
    assert policy.trigger_description == "VIP asks for bulk discount"
    assert policy.rule == "Always offer 10% for 3+ units\nApply only to wholesale"


@pytest.mark.asyncio
async def test_multi_line_with_blank_lines() -> None:
    """Blank lines between generalization lines should be preserved or stripped appropriately."""
    distiller = PolicyDistiller()
    generalization = "Trigger line\n\nRule line after blank"
    policy = await distiller.distill_from_text(
        question="q", answer="a", generalization=generalization,
    )
    assert policy.trigger_description == "Trigger line"
    assert "Rule line after blank" in policy.rule


@pytest.mark.asyncio
async def test_empty_generalization_produces_empty_trigger_and_rule() -> None:
    """Empty generalization should not crash — returns empty strings."""
    distiller = PolicyDistiller()
    policy = await distiller.distill_from_text(
        question="Will this crash?",
        answer="No, it should not",
        generalization="",
    )
    assert policy.trigger_description == ""
    assert policy.rule == ""


@pytest.mark.asyncio
async def test_whitespace_only_generalization() -> None:
    """Whitespace-only generalization should be treated like empty after strip."""
    distiller = PolicyDistiller()
    policy = await distiller.distill_from_text(
        question="Whitespace?",
        answer="Yes",
        generalization="   \n  \n  ",
    )
    assert policy.trigger_description == ""
    assert policy.rule == ""


@pytest.mark.asyncio
async def test_question_and_answer_ignored_in_output() -> None:
    """question and answer parameters are metadata for the owner, not part of Policy model."""
    distiller = PolicyDistiller()
    policy = await distiller.distill_from_text(
        question="VIP asks X",
        answer="Owner answers Y",
        generalization="Rule: always do Z",
    )
    # The Policy model does not have question/answer fields — they're ignored.
    assert policy.trigger_description == "Rule: always do Z"
    assert policy.rule == "Rule: always do Z"
    assert policy.source_query_id is None


@pytest.mark.asyncio
async def test_policy_distiller_lives_in_cognitive_and_has_no_forbidden_imports() -> None:
    """Verifies the module-level constraint: no infra/application/behavior imports."""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "src" / "diana" / "cognitive" / "policy_distiller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = {"aiogram", "diana.infrastructure", "diana.application", "diana.behavior", "diana.llm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, f"forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            prefix = node.module.split(".")[0]
            assert prefix not in forbidden, f"forbidden import: {node.module}"

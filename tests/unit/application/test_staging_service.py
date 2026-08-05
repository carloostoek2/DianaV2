"""StagingService: correction capture, promote to example/policy, discard.

Uses mocked repos at the infrastructure boundary (StagingCandidateRepo,
ExamplesRepo, PoliciesRepo all require a SQLAlchemy session factory).
Service logic is tested end-to-end — no mocks inside the service itself.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock

from diana.application.staging_service import StagingService


def _fake_staging_row(
    *,
    candidate_id: UUID | None = None,
    status: str = "pending",
    candidate_type: str = "example",
    payload: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=candidate_id or uuid4(),
        status=status,
        candidate_type=candidate_type,
        payload=payload or {
            "original_draft": "old draft",
            "corrected_text": "new text",
            "context": {"turn_text": "VIP message"},
        },
    )


def _fake_example_row(example_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=example_id or uuid4())


def _fake_orm_policy(
    policy_id: UUID | None = None,
    query_id: UUID | None = None,
    scope: str = "all",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=policy_id or uuid4(),
        trigger_description="test trigger",
        rule="test rule",
        scope=scope,
        is_active=True,
        source_query_id=query_id,
        created_at=None,
    )


@pytest.fixture
def repos() -> dict[str, AsyncMock]:
    return {
        "staging": AsyncMock(),
        "examples": AsyncMock(),
        "policies": AsyncMock(),
    }


@pytest.fixture
def service(repos: dict[str, AsyncMock]) -> StagingService:
    return StagingService(
        staging_repo=repos["staging"],
        examples_repo=repos["examples"],
        policies_repo=repos["policies"],
    )


# --- save_correction ---


@pytest.mark.asyncio
async def test_save_correction_creates_pending_candidate(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    turn_id = uuid4()
    fake_row = _fake_staging_row()
    repos["staging"].insert.return_value = fake_row

    result = await service.save_correction(
        turn_id=turn_id,
        original_draft="old draft",
        corrected_text="new text",
        context={"turn_text": "VIP says hi"},
    )

    repos["staging"].insert.assert_awaited_once_with(
        "example",
        {
            "original_draft": "old draft",
            "corrected_text": "new text",
            "context": {"turn_text": "VIP says hi"},
            "channel_type": None,
        },
        turn_id,
    )
    assert result is fake_row


@pytest.mark.asyncio
async def test_save_correction_records_channel_type(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    """REQ-ATN-13: atencion corrections carry channel_type in the payload."""
    turn_id = uuid4()
    repos["staging"].insert.return_value = _fake_staging_row()

    await service.save_correction(
        turn_id=turn_id,
        original_draft="old draft",
        corrected_text="new text",
        context={"turn_text": "cliente dice hola"},
        channel_type="atencion",
    )

    insert_kwargs = repos["staging"].insert.await_args.args
    assert insert_kwargs[1]["channel_type"] == "atencion"


# --- promote_to_example ---


@pytest.mark.asyncio
async def test_promote_to_example_happy_path(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    candidate_id = uuid4()
    payload = {
        "original_draft": "old draft",
        "corrected_text": "new text",
        "context": {"turn_text": "VIP says hi"},
    }
    repos["staging"].get_by_id.return_value = _fake_staging_row(
        candidate_id=candidate_id, payload=payload
    )
    fake_example = _fake_example_row()
    repos["examples"].insert.return_value = fake_example
    repos["staging"].update_status.return_value = True

    result = await service.promote_to_example(candidate_id=candidate_id)

    repos["examples"].insert.assert_awaited_once_with(
        turn_text="VIP says hi",
        draft_text="old draft",
        corrected_text="new text",
        context=payload["context"],
        is_counter_example=False,
    )
    repos["staging"].update_status.assert_awaited_once_with(candidate_id, "promoted")
    assert result is fake_example


@pytest.mark.asyncio
async def test_promote_to_example_blocks_atencion_candidate(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    """REQ-ATN-13: atencion-originated candidates never reach the VIP bank."""
    candidate_id = uuid4()
    payload = {
        "original_draft": "old draft",
        "corrected_text": "new text",
        "context": {"turn_text": "cliente dice hola"},
        "channel_type": "atencion",
    }
    repos["staging"].get_by_id.return_value = _fake_staging_row(
        candidate_id=candidate_id, payload=payload
    )

    with pytest.raises(ValueError, match="atencion candidates"):
        await service.promote_to_example(candidate_id=candidate_id)

    # neither inserted into examples nor marked promoted — stays pending
    repos["examples"].insert.assert_not_awaited()
    repos["staging"].update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_promote_to_example_vip_candidate_promotes(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    """REQ-ATN-13: explicit VIP channel candidate promotes normally."""
    candidate_id = uuid4()
    payload = {
        "original_draft": "old draft",
        "corrected_text": "new text",
        "context": {"turn_text": "VIP says hi"},
        "channel_type": "vip",
    }
    repos["staging"].get_by_id.return_value = _fake_staging_row(
        candidate_id=candidate_id, payload=payload
    )
    fake_example = _fake_example_row()
    repos["examples"].insert.return_value = fake_example
    repos["staging"].update_status.return_value = True

    result = await service.promote_to_example(candidate_id=candidate_id)

    repos["examples"].insert.assert_awaited_once()
    repos["staging"].update_status.assert_awaited_once_with(candidate_id, "promoted")
    assert result is fake_example


@pytest.mark.asyncio
async def test_promote_to_example_candidate_not_found(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    repos["staging"].get_by_id.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.promote_to_example(candidate_id=uuid4())

    repos["examples"].insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_promote_to_example_wrong_status(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    repos["staging"].get_by_id.return_value = _fake_staging_row(status="promoted")

    with pytest.raises(ValueError, match="expected 'pending'"):
        await service.promote_to_example(candidate_id=uuid4())

    repos["examples"].insert.assert_not_awaited()


# --- promote_to_policy ---


@pytest.mark.asyncio
async def test_promote_to_policy_happy_path(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    candidate_id = uuid4()
    query_id = uuid4()
    payload = {"query_id": str(query_id)}
    repos["staging"].get_by_id.return_value = _fake_staging_row(
        candidate_id=candidate_id, payload=payload
    )
    fake_policy = _fake_orm_policy(query_id=query_id, scope="wholesale")
    repos["policies"].insert.return_value = fake_policy
    repos["staging"].update_status.return_value = True

    result = await service.promote_to_policy(
        candidate_id=candidate_id,
        trigger="test trigger",
        rule="test rule",
        scope="wholesale",
    )

    repos["policies"].insert.assert_awaited_once_with(
        trigger_description="test trigger",
        rule="test rule",
        scope="wholesale",
        is_active=True,
        source_query_id=str(query_id),
    )
    repos["staging"].update_status.assert_awaited_once_with(candidate_id, "promoted")

    # Result is a domain Policy, not ORM row
    from diana.cognitive.models import Policy as PolicyDomain

    assert isinstance(result, PolicyDomain)
    assert result.trigger_description == "test trigger"
    assert result.rule == "test rule"
    assert result.scope == "wholesale"
    assert result.source_query_id == query_id


@pytest.mark.asyncio
async def test_promote_to_policy_default_scope(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    candidate_id = uuid4()
    repos["staging"].get_by_id.return_value = _fake_staging_row(candidate_id=candidate_id, payload={})
    repos["policies"].insert.return_value = _fake_orm_policy()

    result = await service.promote_to_policy(
        candidate_id=candidate_id, trigger="x", rule="y"
    )

    assert result.scope == "all"


@pytest.mark.asyncio
async def test_promote_to_policy_candidate_not_found(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    repos["staging"].get_by_id.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.promote_to_policy(candidate_id=uuid4(), trigger="x", rule="y")

    repos["policies"].insert.assert_not_awaited()
    repos["staging"].update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_promote_to_policy_wrong_status(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    repos["staging"].get_by_id.return_value = _fake_staging_row(status="discarded")

    with pytest.raises(ValueError, match="expected 'pending'"):
        await service.promote_to_policy(candidate_id=uuid4(), trigger="x", rule="y")

    repos["policies"].insert.assert_not_awaited()


# --- discard ---


@pytest.mark.asyncio
async def test_discard_happy_path(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    candidate_id = uuid4()
    repos["staging"].get_by_id.return_value = _fake_staging_row(
        candidate_id=candidate_id, status="pending"
    )
    repos["staging"].update_status.return_value = True

    await service.discard(candidate_id=candidate_id)

    repos["staging"].get_by_id.assert_awaited_once_with(candidate_id)
    repos["staging"].update_status.assert_awaited_once_with(candidate_id, "discarded")


@pytest.mark.asyncio
async def test_discard_candidate_not_found(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    repos["staging"].get_by_id.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.discard(candidate_id=uuid4())

    repos["staging"].update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_discard_rejects_non_pending(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    candidate_id = uuid4()
    repos["staging"].get_by_id.return_value = _fake_staging_row(
        candidate_id=candidate_id, status="promoted"
    )

    with pytest.raises(ValueError, match="expected 'pending'"):
        await service.discard(candidate_id=candidate_id)

    repos["staging"].update_status.assert_not_awaited()


# --- list_pending_examples ---


@pytest.mark.asyncio
async def test_list_pending_examples_delegates_to_repo(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    rows = [
        _fake_staging_row(candidate_id=uuid4()),
        _fake_staging_row(candidate_id=uuid4()),
    ]
    repos["staging"].list_pending.return_value = rows

    result = await service.list_pending_examples(limit=5)

    repos["staging"].list_pending.assert_awaited_once_with(
        candidate_type="example", limit=5
    )
    assert result is rows


@pytest.mark.asyncio
async def test_list_pending_examples_default_limit(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    repos["staging"].list_pending.return_value = []

    result = await service.list_pending_examples()

    repos["staging"].list_pending.assert_awaited_once_with(
        candidate_type="example", limit=10
    )
    assert result == []


@pytest.mark.asyncio
async def test_promote_to_example_rejects_non_example_type(
    service: StagingService, repos: dict[str, AsyncMock]
) -> None:
    candidate_id = uuid4()
    repos["staging"].get_by_id.return_value = _fake_staging_row(
        candidate_id=candidate_id,
        candidate_type="policy",
        status="pending",
    )

    with pytest.raises(ValueError, match="example"):
        await service.promote_to_example(candidate_id=candidate_id)

    repos["examples"].insert.assert_not_awaited()
    repos["staging"].update_status.assert_not_awaited()


# --- sandbox should_persist gate ---


@pytest.mark.asyncio
async def test_save_correction_skips_when_sandbox_active(
    repos: dict[str, AsyncMock],
) -> None:

    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    sandbox = SandboxService(profiles=MINIMAL_SIX)
    sandbox.activate(42, "nuevo")
    service = StagingService(
        staging_repo=repos["staging"],
        examples_repo=repos["examples"],
        policies_repo=repos["policies"],
        sandbox=sandbox,
    )
    result = await service.save_correction(
        turn_id=uuid4(),
        original_draft="old",
        corrected_text="new",
        context={},
        chat_id=42,
    )
    assert result is None
    repos["staging"].insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_correction_inserts_when_sandbox_inactive(
    repos: dict[str, AsyncMock],
) -> None:

    from diana.application.sandbox import SandboxService
    # inline six-profile catalog
    MINIMAL_SIX = {
        "nuevo": {"label": "Usuario nuevo", "description": "", "facts": {}, "notes": []},
        "cercano": {
            "label": "VIP cercano",
            "description": "",
            "facts": {"name": "Mateo", "personality": "confiado"},
            "notes": [{"date": "2026-05-10", "text": "Le gusta el trato cercano"}],
        },
        "distante": {
            "label": "VIP reservado",
            "description": "",
            "facts": {"personality": "formal"},
            "notes": [],
        },
        "intenso": {
            "label": "VIP emocional",
            "description": "",
            "facts": {"relationship": "recién separado"},
            "notes": [],
        },
        "vip_largo": {
            "label": "VIP largo",
            "description": "",
            "facts": {"name": "Sofía"},
            "notes": [],
        },
        "inyeccion_previa": {
            "label": "Fixture adversarial",
            "description": "",
            "facts": {"name": "TestUser"},
            "notes": [],
        },
    }

    sandbox = SandboxService(profiles=MINIMAL_SIX)
    service = StagingService(
        staging_repo=repos["staging"],
        examples_repo=repos["examples"],
        policies_repo=repos["policies"],
        sandbox=sandbox,
    )
    fake_row = _fake_staging_row()
    repos["staging"].insert.return_value = fake_row
    result = await service.save_correction(
        turn_id=uuid4(),
        original_draft="old",
        corrected_text="new",
        context={},
        chat_id=42,
    )
    assert result is fake_row
    repos["staging"].insert.assert_awaited_once()

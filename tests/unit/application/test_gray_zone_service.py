"""GrayZoneService: query lifecycle, VIP freeze/unfreeze, expire old queries.

Uses REAL InMemoryVipStore (with get_by_id/freeze_vip/unfreeze_vip) and
REAL PolicyDistiller — zero mocks on business logic. Mocks only at the
infrastructure boundary (GrayZoneQueryRepo and StagingCandidateRepo).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from unittest.mock import ANY, AsyncMock

from diana.application.gray_zone_service import GrayZoneService
from diana.application.memory import InMemoryVipStore
from diana.cognitive.policy_distiller import PolicyDistiller


def _fake_query_row(
    *,
    query_id: UUID | None = None,
    status: str = "open",
    vip_id: UUID | None = None,
    question: str = "default question",
    draft: str = "default draft",
    turn_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=query_id or uuid4(),
        status=status,
        vip_id=vip_id,
        question=question,
        draft=draft,
        turn_id=turn_id or uuid4(),
    )


def _fake_staging_row(
    candidate_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(id=candidate_id or uuid4())


@pytest.fixture
def vip_store() -> InMemoryVipStore:
    return InMemoryVipStore()


@pytest.fixture
async def vip_record(vip_store: InMemoryVipStore) -> SimpleNamespace:
    """Create a VIP in the store and return it with both id and telegram_user_id."""
    return await vip_store.add(10001, display_name="TestVIP")


@pytest.fixture
def query_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def staging_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def distiller() -> PolicyDistiller:
    return PolicyDistiller()


@pytest.fixture
def service(
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
    staging_repo: AsyncMock,
    distiller: PolicyDistiller,
) -> GrayZoneService:
    return GrayZoneService(
        query_repo=query_repo,
        vip_store=vip_store,
        staging_repo=staging_repo,
        distiller=distiller,
        default_timeout_hours=24,
    )


# --- create_query ---


@pytest.mark.asyncio
async def test_create_query_creates_open_query_and_freezes_vip(
    service: GrayZoneService,
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    turn_id = uuid4()
    fake_row = _fake_query_row(vip_id=vip_record.id, turn_id=turn_id)
    query_repo.insert.return_value = fake_row

    result = await service.create_query(
        vip_id=vip_record.id,
        turn_id=turn_id,
        question="What discount for 3+?",
        draft="10% off",
        freeze_duration_hours=48,
    )

    query_repo.insert.assert_awaited_once()
    assert query_repo.insert.call_args[1]["vip_id"] == vip_record.id
    assert query_repo.insert.call_args[1]["question"] == "What discount for 3+?"
    assert query_repo.insert.call_args[1]["draft"] == "10% off"

    # Verify VIP is frozen in the real store
    frozen = await vip_store.get_by_id(vip_record.id)
    assert frozen is not None
    assert frozen.frozen_until is not None
    assert frozen.frozen_until > datetime.now(UTC)

    assert result is fake_row


@pytest.mark.asyncio
async def test_create_query_default_freeze_duration(
    service: GrayZoneService,
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    turn_id = uuid4()
    query_repo.insert.return_value = _fake_query_row(vip_id=vip_record.id, turn_id=turn_id)

    await service.create_query(
        vip_id=vip_record.id, turn_id=turn_id, question="q", draft="d",
    )

    # Default is 24 hours
    frozen = await vip_store.get_by_id(vip_record.id)
    assert frozen is not None
    assert frozen.frozen_until is not None
    # Should be roughly 24 hours from now
    expected_min = datetime.now(UTC) + timedelta(hours=23)
    expected_max = datetime.now(UTC) + timedelta(hours=25)
    assert expected_min <= frozen.frozen_until <= expected_max


@pytest.mark.asyncio
async def test_create_query_atencion_no_vip_no_freeze_keeps_chat_id(
    service: GrayZoneService,
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """F13: atencion create_query(vip_id=None) skips the VIP freeze and stores chat_id."""
    turn_id = uuid4()
    query_repo.insert.return_value = _fake_query_row(vip_id=None, turn_id=turn_id)

    result = await service.create_query(
        vip_id=None,
        turn_id=turn_id,
        question="q",
        draft="d",
        chat_id=4545,
    )

    # No VIP to freeze; no VIP exists, so nothing was frozen.
    assert result is not None
    assert query_repo.insert.call_args[1]["vip_id"] is None
    assert query_repo.insert.call_args[1]["chat_id"] == 4545
    # F15: the log records the real None, never the string "None".
    with caplog.at_level(logging.INFO, logger="diana.application"):
        await service.create_query(
            vip_id=None,
            turn_id=uuid4(),
            question="q",
            draft="d",
            chat_id=4545,
        )
    created = [
        r for r in caplog.records if r.getMessage() == "gray_zone_query_created"
    ]
    assert created
    assert created[0].__dict__.get("vip_id") is None


# --- resolve_with_doctrine ---


@pytest.mark.asyncio
async def test_resolve_with_doctrine_creates_staging_candidate(
    service: GrayZoneService,
    query_repo: AsyncMock,
    staging_repo: AsyncMock,
) -> None:
    query_id = uuid4()
    turn_id = uuid4()
    fake_query = _fake_query_row(query_id=query_id, turn_id=turn_id, question="Which plan?", draft="Basic plan")
    query_repo.get_by_id.return_value = fake_query
    fake_candidate = _fake_staging_row()
    staging_repo.insert.return_value = fake_candidate

    result = await service.resolve_with_doctrine(
        query_id=query_id,
        generalization="Always offer basic plan first",
        rule="Basic plan for new customers",
    )

    query_repo.get_by_id.assert_awaited_once_with(query_id)
    staging_repo.insert.assert_awaited_once()
    assert staging_repo.insert.call_args[0][0] == "policy"
    payload = staging_repo.insert.call_args[0][1]
    assert payload["question"] == "Which plan?"
    assert payload["generalization"] == "Always offer basic plan first"
    assert payload["query_id"] == str(query_id)

    # Query should NOT be closed or unfrozen yet
    query_repo.update_status.assert_not_awaited()
    assert result is fake_candidate


@pytest.mark.asyncio
async def test_resolve_with_doctrine_query_not_found(
    service: GrayZoneService,
    query_repo: AsyncMock,
    staging_repo: AsyncMock,
) -> None:
    query_repo.get_by_id.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await service.resolve_with_doctrine(
            query_id=uuid4(), generalization="x", rule="y",
        )

    staging_repo.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_with_doctrine_wrong_status(
    service: GrayZoneService,
    query_repo: AsyncMock,
    staging_repo: AsyncMock,
) -> None:
    query_repo.get_by_id.return_value = _fake_query_row(status="resolved")

    with pytest.raises(ValueError, match="expected 'open'"):
        await service.resolve_with_doctrine(
            query_id=uuid4(), generalization="x", rule="y",
        )

    staging_repo.insert.assert_not_awaited()


# --- confirm_and_apply ---


@pytest.mark.asyncio
async def test_confirm_and_apply_closes_query_and_unfreezes_vip(
    service: GrayZoneService,
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    query_id = uuid4()
    query_repo.update_status.return_value = True
    query_repo.get_by_id.return_value = _fake_query_row(
        query_id=query_id, status="open", vip_id=vip_record.id,
    )

    # First freeze the VIP (simulate create_query)
    frozen_until = datetime.now(UTC) + timedelta(hours=24)
    await vip_store.freeze_vip(vip_record.id, frozen_until)

    result = await service.confirm_and_apply(query_id=query_id, candidate_id=uuid4())

    query_repo.update_status.assert_awaited_once_with(query_id, "resolved", resolved_at=ANY)
    # VIP should be unfrozen
    vip = await vip_store.get_by_id(vip_record.id)
    assert vip is not None
    assert vip.frozen_until is None

    assert result.status == "open"


@pytest.mark.asyncio
async def test_confirm_and_apply_no_vip_no_unfreeze(
    service: GrayZoneService,
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
) -> None:
    """When query has no vip_id, confirm_and_apply does not call unfreeze."""
    query_id = uuid4()
    query_repo.update_status.return_value = True
    query_repo.get_by_id.return_value = _fake_query_row(
        query_id=query_id, status="open", vip_id=None,
    )

    result = await service.confirm_and_apply(query_id=query_id, candidate_id=uuid4())

    query_repo.update_status.assert_awaited_once()
    assert result is not None


# --- discard_and_close ---


@pytest.mark.asyncio
async def test_discard_and_close_unfreezes_vip_and_closes_query(
    service: GrayZoneService,
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    query_id = uuid4()
    query_repo.get_by_id.return_value = _fake_query_row(
        query_id=query_id, status="open", vip_id=vip_record.id,
    )
    query_repo.update_status.return_value = True

    await vip_store.freeze_vip(vip_record.id, datetime.now(UTC) + timedelta(hours=24))

    result = await service.discard_and_close(query_id=query_id)

    query_repo.update_status.assert_awaited_once_with(query_id, "resolved", resolved_at=ANY)
    vip = await vip_store.get_by_id(vip_record.id)
    assert vip is not None
    assert vip.frozen_until is None
    assert result is not None


@pytest.mark.asyncio
async def test_discard_and_close_no_vip_skips_unfreeze(
    service: GrayZoneService,
    query_repo: AsyncMock,
) -> None:
    query_id = uuid4()
    query_repo.get_by_id.return_value = _fake_query_row(
        query_id=query_id, vip_id=None,
    )
    query_repo.update_status.return_value = True

    # Should not raise even though no VIP is found
    result = await service.discard_and_close(query_id=query_id)
    assert result is not None


@pytest.mark.asyncio
async def test_discard_and_close_returns_original_query(
    service: GrayZoneService,
    query_repo: AsyncMock,
) -> None:
    """discard_and_close returns the original query (no re-fetch)."""
    query_id = uuid4()
    query_repo.get_by_id.return_value = _fake_query_row(query_id=query_id, vip_id=None)
    query_repo.update_status.return_value = True

    result = await service.discard_and_close(query_id=query_id)
    assert result is not None
    assert result.id == query_id


# --- freeze_vip / unfreeze_vip ---


@pytest.mark.asyncio
async def test_freeze_vip_delegates_to_store(
    service: GrayZoneService,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    await service.freeze_vip(vip_id=vip_record.id, duration_hours=12)

    vip = await vip_store.get_by_id(vip_record.id)
    assert vip is not None
    assert vip.frozen_until is not None
    expected_min = datetime.now(UTC) + timedelta(hours=11)
    assert vip.frozen_until > expected_min


@pytest.mark.asyncio
async def test_freeze_vip_default_duration(
    service: GrayZoneService,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    await service.freeze_vip(vip_id=vip_record.id)

    vip = await vip_store.get_by_id(vip_record.id)
    assert vip is not None
    assert vip.frozen_until is not None
    # Default timeout is 24 hours
    expected_min = datetime.now(UTC) + timedelta(hours=23)
    assert vip.frozen_until > expected_min


@pytest.mark.asyncio
async def test_unfreeze_vip_delegates_to_store(
    service: GrayZoneService,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    # First freeze, then unfreeze
    await vip_store.freeze_vip(vip_record.id, datetime.now(UTC) + timedelta(hours=24))
    await service.unfreeze_vip(vip_id=vip_record.id)

    vip = await vip_store.get_by_id(vip_record.id)
    assert vip is not None
    assert vip.frozen_until is None


@pytest.mark.asyncio
async def test_freeze_vip_not_found_raises(
    service: GrayZoneService,
) -> None:
    with pytest.raises(ValueError, match="not found"):
        await service.freeze_vip(vip_id=uuid4())


# --- expire_old_queries ---


@pytest.mark.asyncio
async def test_expire_old_queries_with_expired_rows(
    service: GrayZoneService,
    query_repo: AsyncMock,
    vip_store: InMemoryVipStore,
    vip_record: SimpleNamespace,
) -> None:
    query_id = uuid4()
    expired_row = _fake_query_row(
        query_id=query_id,
        status="open",
        vip_id=vip_record.id,
    )
    query_repo.expire_older_than.return_value = [expired_row]

    # Freeze the VIP first
    await vip_store.freeze_vip(vip_record.id, datetime.now(UTC) + timedelta(hours=24))

    result = await service.expire_old_queries(timeout_hours=48)

    query_repo.expire_older_than.assert_awaited_once_with(48)
    assert len(result) == 1
    assert result[0].id == query_id

    # VIP should be unfrozen
    vip = await vip_store.get_by_id(vip_record.id)
    assert vip is not None
    assert vip.frozen_until is None


@pytest.mark.asyncio
async def test_expire_old_queries_default_timeout(
    service: GrayZoneService,
    query_repo: AsyncMock,
) -> None:
    query_repo.expire_older_than.return_value = []

    result = await service.expire_old_queries()

    query_repo.expire_older_than.assert_awaited_once_with(24)
    assert result == []


@pytest.mark.asyncio
async def test_expire_old_queries_no_expired_returns_empty(
    service: GrayZoneService,
    query_repo: AsyncMock,
) -> None:
    query_repo.expire_older_than.return_value = []

    result = await service.expire_old_queries(timeout_hours=24)

    assert result == []


@pytest.mark.asyncio
async def test_expire_old_queries_skips_vip_without_vip_id(
    service: GrayZoneService,
    query_repo: AsyncMock,
) -> None:
    """Expired query with vip_id=None should not crash on unfreeze."""
    query_repo.expire_older_than.return_value = [
        _fake_query_row(status="open", vip_id=None),
    ]

    result = await service.expire_old_queries(timeout_hours=24)

    assert len(result) == 1

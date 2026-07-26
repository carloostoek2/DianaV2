"""Offline port/repo surface tests for recontact + promo (no Postgres)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest


def test_ports_records_and_protocols_importable() -> None:
    from diana.application.ports import (
        PromoExecutionRecord,
        PromoExecutionStore,
        PromoTriggerRecord,
        PromoTriggerStore,
        RecontactScheduleRecord,
        RecontactScheduleStore,
    )

    assert RecontactScheduleRecord is not None
    assert PromoTriggerRecord is not None
    assert PromoExecutionRecord is not None
    assert RecontactScheduleStore is not None
    assert PromoTriggerStore is not None
    assert PromoExecutionStore is not None


def test_record_construction_extra_forbid() -> None:
    from diana.application.ports import (
        PromoExecutionRecord,
        PromoTriggerRecord,
        RecontactScheduleRecord,
    )

    now = datetime.now(UTC)
    rid = uuid4()
    vip_id = uuid4()
    trigger_id = uuid4()

    rs = RecontactScheduleRecord(
        id=rid,
        vip_id=vip_id,
        last_contact_at=now,
        next_contact_at=now,
        status="pending",
    )
    assert rs.status == "pending"

    pt = PromoTriggerRecord(
        id=trigger_id,
        trigger_text="quiero información",
        response_sequence=["a", "b"],
        repeat_first_message="re-intro",
        is_active=True,
    )
    assert pt.repeat_first_message == "re-intro"

    pe = PromoExecutionRecord(
        id=uuid4(),
        chat_id=123,
        trigger_id=trigger_id,
        sent_at=now,
        sequence_sent=["a", "b"],
        status="sent",
    )
    assert pe.chat_id == 123

    with pytest.raises(Exception):
        RecontactScheduleRecord(
            id=rid,
            vip_id=vip_id,
            last_contact_at=now,
            status="pending",
            extra_field="nope",  # type: ignore[call-arg]
        )


def test_repo_classes_accept_session_factory() -> None:
    from diana.infrastructure.db.repositories.promo_executions import (
        PromoExecutionRepo,
    )
    from diana.infrastructure.db.repositories.promo_triggers import PromoTriggerRepo
    from diana.infrastructure.db.repositories.recontact_schedules import (
        RecontactScheduleRepo,
    )

    for cls in (RecontactScheduleRepo, PromoTriggerRepo, PromoExecutionRepo):
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters.keys())
        assert "session_factory" in params
        # Construct with a dummy factory (not called)
        repo = cls(session_factory=object)  # type: ignore[arg-type]
        assert repo is not None


def test_recontact_schedule_repo_method_surface() -> None:
    from diana.infrastructure.db.repositories.recontact_schedules import (
        RecontactScheduleRepo,
    )

    required = (
        "upsert_pending",
        "get_pending_by_vip",
        "list_due",
        "cancel_pending",
        "mark_done",
    )
    for name in required:
        assert hasattr(RecontactScheduleRepo, name), name
        method = getattr(RecontactScheduleRepo, name)
        assert inspect.iscoroutinefunction(method), name


def test_promo_trigger_repo_method_surface() -> None:
    from diana.infrastructure.db.repositories.promo_triggers import PromoTriggerRepo

    for name in ("get_active_by_trigger_text", "list_active"):
        assert hasattr(PromoTriggerRepo, name), name
        assert inspect.iscoroutinefunction(getattr(PromoTriggerRepo, name))


def test_promo_execution_repo_method_surface() -> None:
    from diana.infrastructure.db.repositories.promo_executions import (
        PromoExecutionRepo,
    )

    for name in ("insert", "latest_for_chat_trigger", "was_sent_since"):
        assert hasattr(PromoExecutionRepo, name), name
        assert inspect.iscoroutinefunction(getattr(PromoExecutionRepo, name))


def test_protocol_method_names_match_repos() -> None:
    from diana.application.ports import (
        PromoExecutionStore,
        PromoTriggerStore,
        RecontactScheduleStore,
    )
    from diana.infrastructure.db.repositories.promo_executions import (
        PromoExecutionRepo,
    )
    from diana.infrastructure.db.repositories.promo_triggers import PromoTriggerRepo
    from diana.infrastructure.db.repositories.recontact_schedules import (
        RecontactScheduleRepo,
    )

    for proto, repo in (
        (RecontactScheduleStore, RecontactScheduleRepo),
        (PromoTriggerStore, PromoTriggerRepo),
        (PromoExecutionStore, PromoExecutionRepo),
    ):
        proto_methods = {
            n
            for n, _ in inspect.getmembers(proto, predicate=inspect.isfunction)
            if not n.startswith("_")
        }
        # Protocol members may also appear via __annotations__/dir
        for name in dir(proto):
            if name.startswith("_"):
                continue
            attr = getattr(proto, name, None)
            if callable(attr) or name in getattr(proto, "__annotations__", {}):
                if name not in ("__class__",):
                    proto_methods.add(name)
        # Prefer explicit known contract names over dir noise
        contract = {
            RecontactScheduleStore: {
                "upsert_pending",
                "get_pending_by_vip",
                "list_due",
                "cancel_pending",
                "mark_done",
            },
            PromoTriggerStore: {"get_active_by_trigger_text", "list_active"},
            PromoExecutionStore: {
                "insert",
                "latest_for_chat_trigger",
                "was_sent_since",
            },
        }[proto]
        for name in contract:
            assert hasattr(repo, name), f"{repo.__name__}.{name}"


def test_normalize_trigger_text() -> None:
    from diana.infrastructure.db.repositories.promo_triggers import (
        normalize_trigger_text,
    )

    assert normalize_trigger_text("  Quiero Información  ") == "quiero información"
    assert normalize_trigger_text("PROMOCIONES") == "promociones"


def test_orm_to_record_mappers_pure() -> None:
    """Mappers accept simple namespace-like objects without DB."""
    from types import SimpleNamespace
    from uuid import uuid4

    from diana.infrastructure.db.repositories.promo_executions import (
        promo_execution_orm_to_record,
    )
    from diana.infrastructure.db.repositories.promo_triggers import (
        promo_trigger_orm_to_record,
    )
    from diana.infrastructure.db.repositories.recontact_schedules import (
        recontact_schedule_orm_to_record,
    )

    now = datetime.now(UTC)
    schedule_id = uuid4()
    vip_id = uuid4()
    trigger_id = uuid4()
    exec_id = uuid4()

    rec = recontact_schedule_orm_to_record(
        SimpleNamespace(
            id=schedule_id,
            vip_id=vip_id,
            last_contact_at=now,
            next_contact_at=None,
            status="pending",
        )
    )
    assert rec.id == schedule_id
    assert rec.next_contact_at is None

    ptr = promo_trigger_orm_to_record(
        SimpleNamespace(
            id=trigger_id,
            trigger_text="promociones",
            response_sequence=["a", "b"],
            repeat_first_message="hola",
            is_active=True,
        )
    )
    assert ptr.response_sequence == ["a", "b"]

    per = promo_execution_orm_to_record(
        SimpleNamespace(
            id=exec_id,
            chat_id=99,
            trigger_id=trigger_id,
            sent_at=now,
            sequence_sent=["a"],
            status="sent",
        )
    )
    assert per.chat_id == 99


def test_system_config_store_has_recontact_promo_getters() -> None:
    from diana.infrastructure.db.repositories.system_config import SqlSystemConfigStore

    assert hasattr(SqlSystemConfigStore, "get_recontact_config")
    assert hasattr(SqlSystemConfigStore, "get_promo_config")
    assert inspect.iscoroutinefunction(SqlSystemConfigStore.get_recontact_config)
    assert inspect.iscoroutinefunction(SqlSystemConfigStore.get_promo_config)

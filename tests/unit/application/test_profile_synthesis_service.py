"""ProfileSynthesisService — 3 prompt blocks, confidence gating, weight revalidation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from diana.application.ports import VipProfileRecord
from diana.application.profile_synthesis_service import (
    ProfileSynthesisService,
    SensitivityItem,
    SynthesisOutput,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _record(**kw) -> VipProfileRecord:
    data = dict(
        vip_id=uuid4(),
        stable_traits={"dedicada": True},
        recent_trend={"cercania": 0.8},
        sensitivities=[{"trait": "apertura", "weight": 0.6}],
        version=1,
        last_synthesized_at=_now() - timedelta(days=7),
        synthesis_trigger=None,
    )
    data.update(kw)
    return VipProfileRecord(**data)


class _FakeLLM:
    """Returns a fixed SynthesisOutput or raises (test switch)."""

    def __init__(self, output=None, exc: Exception | None = None) -> None:
        self._output = output
        self._exc = exc
        self.calls: list[list] = []

    async def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(messages)
        if self._exc is not None:
            raise self._exc
        return self._output


class _FakeProfileStore:
    def __init__(self, *, persisted: VipProfileRecord | None = None) -> None:
        self.persisted = persisted
        self.saved: list[dict] = []

    async def get_by_vip(self, vip_id: UUID) -> VipProfileRecord | None:
        return self.persisted

    async def get_or_create(self, vip_id: UUID) -> VipProfileRecord:
        return self.persisted or _record(vip_id=vip_id, version=0)

    async def save_synthesis_result(
        self, vip_id, *, previous, next, changes_summary
    ) -> VipProfileRecord:
        self.saved.append(
            {
                "vip_id": vip_id,
                "previous": previous,
                "next": next,
                "changes_summary": changes_summary,
            }
        )
        return next


class _FakeMemories:
    def __init__(self, facts: list | None = None) -> None:
        self.facts = list(facts or [])

    async def list_by_vip_since(self, vip_id, *, since, limit=200):
        return self.facts


class _FakeCorrections:
    def __init__(self, signals: list | None = None) -> None:
        self.signals = list(signals or [])

    async def list_corrections_by_vip_since(self, vip_id, *, since, limit=50):
        return self.signals


def _service(*, llm=None, store=None, memories=None, corrections=None, conf_min=0.6):
    return ProfileSynthesisService(
        llm=llm or _FakeLLM(),
        profile_store=store or _FakeProfileStore(),
        memories=memories or _FakeMemories(),
        corrections=corrections or _FakeCorrections(),
        confidence_min=conf_min,
    )


def test_prompt_has_three_explicit_blocks() -> None:
    svc = _service()
    current = _record()
    facts = [{"category": "identidad", "content": {"texto": "Vive en CDMX"}}]
    signals = [
        {
            "created_at": "2026-08-01T10:00:00+00:00",
            "payload": {"corrected_text": "mejor tono"},
        }
    ]
    messages = svc._build_prompt(current, facts, signals)  # noqa: SLF001
    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    user = json.loads(messages[1]["content"])
    assert set(user.keys()) == {
        "current_profile",
        "new_episodic_facts",
        "feedback_signals",
    }  # exactly the three blocks, never mixed
    assert user["new_episodic_facts"] == facts
    assert user["feedback_signals"] == signals
    assert "vip_id" not in user["current_profile"]  # exclude vip_id
    # S6: confidence is REQUIRED (a numeric [0,1] value) — never "optional".
    assert "ALWAYS" in system
    assert "between 0 and 1" in system
    assert "optional" not in system
    # Fix round nit: the decay rules (A10) are pinned — a regression that
    # strips them would fail here.
    assert "DECAY" in system
    assert "0.3" in system  # remove-from-sensitivities threshold
    assert "sensitivities" in system


@pytest.mark.asyncio
async def test_high_confidence_overwrites_and_versions() -> None:
    current = _record(version=2)
    store = _FakeProfileStore(persisted=current)
    output = SynthesisOutput(
        stable_traits={"dedicada": False, "nueva": True},
        recent_trend={"cercania": 0.9},
        sensitivities=[SensitivityItem(trait="apertura", weight=0.8)],
        changes_summary="más apertura",
        confidence=0.9,
    )
    svc = _service(llm=_FakeLLM(output=output), store=store)
    report = await svc.synthesize(current.vip_id, "volume")
    assert report.status == "ok"
    assert report.version == 3
    saved = store.saved[0]
    assert saved["previous"] is current  # snapshot provided
    assert saved["next"].version == 3
    assert saved["next"].stable_traits == {"dedicada": False, "nueva": True}
    assert saved["next"].sensitivities == [
        {"trait": "apertura", "weight": 0.8, "evidence_count": 0}
    ]
    assert saved["changes_summary"] == "más apertura"


@pytest.mark.asyncio
async def test_low_confidence_only_recent_trend() -> None:
    current = _record(version=2)
    store = _FakeProfileStore(persisted=current)
    output = SynthesisOutput(
        stable_traits={"ruido": True},
        recent_trend={"cercania": 0.3},
        sensitivities=[SensitivityItem(trait="inventado", weight=0.9)],
        changes_summary="ruido",
        confidence=0.3,
    )
    svc = _service(llm=_FakeLLM(output=output), store=store)
    report = await svc.synthesize(current.vip_id, "volume")
    assert report.status == "low_confidence"
    assert report.version == 2  # no bump
    saved = store.saved[0]
    assert saved["previous"] is None  # no snapshot on the low branch
    assert saved["next"].stable_traits == current.stable_traits  # intact
    assert saved["next"].sensitivities == current.sensitivities  # intact
    assert saved["next"].recent_trend == {"cercania": 0.3}  # only recent_trend
    assert saved["next"].version == 2
    assert saved["changes_summary"] is None
    # Both branches advance last_synthesized_at.
    assert saved["next"].last_synthesized_at is not None


@pytest.mark.asyncio
async def test_none_confidence_treated_as_low() -> None:
    current = _record(version=1)
    store = _FakeProfileStore(persisted=current)
    output = SynthesisOutput(
        stable_traits={"x": 1},
        recent_trend={"y": 2},
        sensitivities=[],
        confidence=None,  # fail-safe
    )
    svc = _service(llm=_FakeLLM(output=output), store=store)
    report = await svc.synthesize(current.vip_id, "strong_signal")
    assert report.status == "low_confidence"
    saved = store.saved[0]
    assert saved["previous"] is None
    assert saved["next"].stable_traits == current.stable_traits


@pytest.mark.asyncio
async def test_sensitivities_out_of_range_dropped() -> None:
    current = _record(version=1)
    store = _FakeProfileStore(persisted=current)
    output = SynthesisOutput(
        stable_traits={},
        recent_trend={},
        sensitivities=[
            SensitivityItem(trait="ok", weight=0.5),
            SensitivityItem(trait="fuera", weight=1.5),  # out of [0,1]
        ],
        confidence=0.9,
    )
    svc = _service(llm=_FakeLLM(output=output), store=store)
    report = await svc.synthesize(current.vip_id, "volume")
    assert report.status == "ok"
    persisted_sens = store.saved[0]["next"].sensitivities
    assert persisted_sens == [{"trait": "ok", "weight": 0.5, "evidence_count": 0}]


@pytest.mark.asyncio
async def test_first_synthesis_no_snapshot() -> None:
    """get_by_vip None → previous=None even on high confidence (A7)."""
    store = _FakeProfileStore(persisted=None)
    output = SynthesisOutput(
        stable_traits={"primer": True},
        recent_trend={},
        sensitivities=[],
        confidence=0.9,
    )
    svc = _service(llm=_FakeLLM(output=output), store=store)
    vip = uuid4()
    report = await svc.synthesize(vip, "session_close")
    assert report.status == "ok"
    saved = store.saved[0]
    assert saved["previous"] is None
    assert saved["next"].version == 1  # default 0 + 1


@pytest.mark.asyncio
async def test_llm_failure_raises_loud_no_write() -> None:
    store = _FakeProfileStore(persisted=_record())
    svc = _service(llm=_FakeLLM(exc=ValueError("bad json")), store=store)
    with pytest.raises(ValueError):
        await svc.synthesize(uuid4(), "volume")
    assert store.saved == []  # no write on failure


@pytest.mark.asyncio
async def test_last_synthesized_at_captured_before_reads_s2() -> None:
    """S2: ``now`` is captured BEFORE the facts/signals reads, so facts created
    during the LLM window never fall into the gap (they would be skipped both
    in this run and the next, since last_synthesized_at already advanced)."""
    current = _record(version=1)
    store = _FakeProfileStore(persisted=current)
    read_marker: dict = {}

    class _MarkingMemories(_FakeMemories):
        async def list_by_vip_since(self, vip_id, *, since, limit=200):
            read_marker["facts_read_at"] = datetime.now(UTC)
            return await super().list_by_vip_since(vip_id, since=since, limit=limit)

    output = SynthesisOutput(
        stable_traits={"x": True}, recent_trend={}, sensitivities=[],
        confidence=0.9,
    )
    svc = _service(
        llm=_FakeLLM(output=output), store=store, memories=_MarkingMemories()
    )
    report = await svc.synthesize(current.vip_id, "volume")
    assert report.status == "ok"
    saved_at = store.saved[0]["next"].last_synthesized_at
    assert saved_at is not None
    # The written last_synthesized_at predates the facts read — captured before
    # the reads, not after the LLM window.
    assert saved_at <= read_marker["facts_read_at"]


@pytest.mark.asyncio
async def test_high_confidence_changes_summary_not_none_when_empty_s7() -> None:
    """S7: a high-confidence run persists a changes_summary even when the LLM
    returns an empty string — the audit trail (1.4) never stores NULL."""
    current = _record(version=1)
    store = _FakeProfileStore(persisted=current)
    output = SynthesisOutput(
        stable_traits={"x": True}, recent_trend={}, sensitivities=[],
        changes_summary="",  # LLM sent nothing
        confidence=0.9,
    )
    svc = _service(llm=_FakeLLM(output=output), store=store)
    report = await svc.synthesize(current.vip_id, "volume")
    assert report.status == "ok"
    saved = store.saved[0]
    assert saved["changes_summary"] is not None
    assert saved["changes_summary"].strip() != ""


def test_apply_overrides() -> None:
    svc = _service()
    assert svc._confidence_min == 0.6  # noqa: SLF001
    svc.apply_overrides({"confidence_min": 0.7})
    assert svc._confidence_min == 0.7  # noqa: SLF001
    svc.apply_overrides({"confidence_min": "no"})  # invalid ignored
    assert svc._confidence_min == 0.7  # noqa: SLF001
    svc.apply_overrides({"confidence_min": 3.0})  # clamped to [0,1]
    assert svc._confidence_min == 1.0  # noqa: SLF001
    svc.apply_overrides(None)  # non-dict no-op
    assert svc._confidence_min == 1.0  # noqa: SLF001


def test_import_purity_no_aiogram_no_infra() -> None:
    import ast
    from pathlib import Path

    import diana.application.profile_synthesis_service as mod

    tree = ast.parse(
        Path(mod.__file__).read_text(encoding="utf-8"), filename=str(mod.__file__)
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "aiogram" not in imported
    assert "infrastructure" not in imported

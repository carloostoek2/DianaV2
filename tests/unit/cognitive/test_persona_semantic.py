"""PersonaSemanticShadow — background semantic catalog shadow (ítem 3, E1).

SHADOW: only measures (ids + scores in a log); never touches the prompt, the
retrieved map or the trace; never indexes ``nota_privada``.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from diana.cognitive import persona_semantic as ps_mod
from diana.cognitive.operacion import OperacionHit
from diana.cognitive.persona_catalog import load_persona_catalog, get_persona_atencion_catalog
from diana.cognitive.persona_semantic import (
    PersonaSemanticShadow,
    ShadowSnapshot,
    build_shadow_index_texts,
    build_shadow_snapshot,
)

SECRET = "SECRETO-NOTA-XYZ"


class _FakeEmbedder:
    model_name = "fake-mini"

    def __init__(self, loaded: bool = True) -> None:
        self.is_loaded = loaded
        self.texts: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        v = [0.0] * 8
        for tok in text.lower().split():
            v[sum(map(ord, tok)) % 8] += 1.0  # determinista (no hash() aleatorio)
        return v


class _Provider:
    def __init__(self, by_channel):
        self.by_channel = by_channel

    async def get_catalog(self, channel):
        return self.by_channel[channel]


def _vip():
    cat = deepcopy(load_persona_catalog())
    cat["persona_facts"][0]["nota_privada"] = SECRET
    cat["operacion"] = [{"id": "lucien", "alias": ["Lucien"], "hecho": "Lucien es el bot."}]
    return cat


def _atn():
    return deepcopy(get_persona_atencion_catalog())


def _snap(channel: str, text: str, **kw) -> ShadowSnapshot:
    return ShadowSnapshot(
        turn_id=str(uuid4()),
        channel_type=channel,
        text=text,
        retrieved_fact_hechos=kw.get("hechos", ()),
        retrieved_policy_ids=kw.get("policy_ids", ()),
        operacion_ids=kw.get("operacion_ids", ()),
    )


async def _drain(shadow):
    await asyncio.gather(*shadow._tasks.values())


def _records(caplog, msg):
    return [r for r in caplog.records if r.getMessage() == msg]


async def test_index_never_contains_nota_privada(caplog):
    emb = _FakeEmbedder()
    shadow = PersonaSemanticShadow(emb, _Provider({"vip": _vip()}))
    with caplog.at_level("INFO", logger="diana.cognitive.shadow"):
        shadow.schedule(_snap("vip", "hola"))
        await _drain(shadow)
    assert emb.texts  # the index was built
    assert all(SECRET not in t for t in emb.texts)
    assert SECRET not in caplog.text


async def test_schedule_is_fast():
    shadow = PersonaSemanticShadow(_FakeEmbedder(), _Provider({"vip": _vip()}))
    t0 = time.perf_counter()
    shadow.schedule(_snap("vip", "hola"))
    assert (time.perf_counter() - t0) * 1000 < 10.0
    await _drain(shadow)


async def test_log_has_ids_and_scores_only(caplog):
    text = "mensaje-del-cliente-unico estudios psicologia"
    shadow = PersonaSemanticShadow(_FakeEmbedder(), _Provider({"vip": _vip()}))
    with caplog.at_level("INFO", logger="diana.cognitive.shadow"):
        shadow.schedule(_snap("vip", text))
        await _drain(shadow)
    recs = _records(caplog, "persona_semantic_shadow")
    assert len(recs) == 1
    top = recs[0].top
    assert 0 < len(top) <= 3
    assert all(set(entry) == {"section", "id", "score"} for entry in top)
    assert "mensaje-del-cliente-unico" not in caplog.text
    assert recs[0].model_name == "fake-mini"
    assert recs[0].index_size > 0


async def test_channel_isolation_vip_vs_atencion():
    vip, atn = _vip(), _atn()
    shadow = PersonaSemanticShadow(_FakeEmbedder(), _Provider({"vip": vip, "atencion": atn}))
    shadow.schedule(_snap("vip", "hola"))
    shadow.schedule(_snap("atencion", "hola"))
    await _drain(shadow)
    vip_ids = {k for _, k in shadow._index["vip"][1]}
    atn_ids = {k for _, k in shadow._index["atencion"][1]}
    expected_vip = {i for _, i, _ in build_shadow_index_texts(vip)}
    expected_atn = {i for _, i, _ in build_shadow_index_texts(atn)}
    assert vip_ids == expected_vip and atn_ids == expected_atn
    assert not (atn_ids & (expected_vip - expected_atn))
    assert not (vip_ids & (expected_atn - expected_vip))


async def test_rebuilds_index_only_when_catalog_identity_changes():
    emb = _FakeEmbedder()
    cat = _vip()
    provider = _Provider({"vip": cat})
    shadow = PersonaSemanticShadow(emb, provider)
    n_index = len(build_shadow_index_texts(cat))
    shadow.schedule(_snap("vip", "uno"))
    await _drain(shadow)
    shadow.schedule(_snap("vip", "dos"))
    await _drain(shadow)
    assert len(emb.texts) == n_index + 2  # index once + 2 queries
    provider.by_channel["vip"] = deepcopy(cat)  # new object → rebuild
    shadow.schedule(_snap("vip", "tres"))
    await _drain(shadow)
    assert len(emb.texts) == 2 * n_index + 3


async def test_skips_when_model_not_loaded(caplog):
    emb = _FakeEmbedder(loaded=False)
    shadow = PersonaSemanticShadow(emb, _Provider({"vip": _vip()}))
    with caplog.at_level("INFO", logger="diana.cognitive.shadow"):
        shadow.schedule(_snap("vip", "hola"))
        await _drain(shadow)
    assert emb.texts == []
    recs = _records(caplog, "persona_semantic_shadow_skipped")
    assert recs and recs[0].reason == "model_not_loaded"


async def test_exception_in_run_is_swallowed_and_logged(caplog):
    class _Boom:
        async def get_catalog(self, channel):
            raise RuntimeError("db down")

    shadow = PersonaSemanticShadow(_FakeEmbedder(), _Boom())
    with caplog.at_level("INFO", logger="diana.cognitive.shadow"):
        shadow.schedule(_snap("vip", "hola"))
        await _drain(shadow)  # does not raise
    assert _records(caplog, "persona_semantic_shadow_failed")


async def test_one_task_per_channel_drops_when_busy(caplog):
    gate = asyncio.Event()

    class _SlowProvider(_Provider):
        async def get_catalog(self, channel):
            await gate.wait()
            return await super().get_catalog(channel)

    shadow = PersonaSemanticShadow(_FakeEmbedder(), _SlowProvider({"vip": _vip(), "atencion": _atn()}))
    with caplog.at_level("INFO", logger="diana.cognitive.shadow"):
        assert shadow.schedule(_snap("vip", "uno")) is True
        assert shadow.schedule(_snap("vip", "dos")) is False
        assert shadow.schedule(_snap("atencion", "uno")) is True  # other channel is free
        gate.set()
        await _drain(shadow)
    assert _records(caplog, "persona_semantic_shadow_dropped")
    assert shadow.schedule(_snap("vip", "tres")) is True
    await _drain(shadow)


def test_snapshot_copies_strings_only():
    turn = SimpleNamespace(turn_id=uuid4(), channel_type="vip", text="hola")
    retrieved = {
        "knowledge.persona_facts": [{"hecho": "H1", "tema": "t"}],
        "knowledge.policy": ["Trigger: no_ex | Rule: Nunca hablo de mi ex"],
    }
    hits = [OperacionHit(id="lucien", alias="Lucien", hecho="Lucien es el bot.")]
    snap = build_shadow_snapshot(turn, retrieved, hits)
    retrieved["knowledge.persona_facts"][0]["hecho"] = "MUTATED"
    retrieved["knowledge.policy"].append("Trigger: otra | Rule: x")
    hits.append(OperacionHit(id="otro", alias="Otro", hecho="x"))
    assert snap.retrieved_fact_hechos == ("H1",)
    assert snap.retrieved_policy_ids == ("no_ex",)
    assert snap.operacion_ids == ("lucien",)
    for field in (snap.retrieved_fact_hechos, snap.retrieved_policy_ids, snap.operacion_ids):
        assert isinstance(field, tuple) and all(isinstance(x, str) for x in field)
    assert isinstance(snap.turn_id, str) and snap.text == "hola"


def test_already_retrieved_parses_catalog_policy_ids():
    cat = _vip()
    pol = cat["policies"][0]
    fact = cat["persona_facts"][1]
    turn = SimpleNamespace(turn_id=uuid4(), channel_type="vip", text="x")
    retrieved = {
        "knowledge.policy": [
            f"Trigger: {pol['id']} | Rule: {pol['regla']}",
            "Trigger: una descripción de BD | Rule: r",  # DB line: not a catalog id
        ],
        "knowledge.persona_facts": [{"hecho": fact["hecho"], "tema": "t"}],
    }
    snap = build_shadow_snapshot(turn, retrieved, [OperacionHit("lucien", "Lucien", "h")])
    top = [
        {"section": "policies", "id": pol["id"], "score": 0.9},
        {"section": "persona_facts", "id": fact["id"], "score": 0.8},
        {"section": "operacion", "id": "lucien", "score": 0.7},
        {"section": "persona_facts", "id": cat["persona_facts"][2]["id"], "score": 0.6},
    ]
    flags = ps_mod._already_retrieved(top, snap, cat)  # noqa: SLF001
    assert flags == [True, True, True, False]
    assert "una descripción de BD" in snap.retrieved_policy_ids  # kept, but never matches an id


def test_build_shadow_index_texts_allow_list():
    cat = _vip()
    entries = build_shadow_index_texts(cat)
    sections = {s for s, _, _ in entries}
    assert sections <= {"persona_facts", "policies", "operacion"}
    assert {"persona_facts", "policies", "operacion"} == sections
    assert all(SECRET not in text for _, _, text in entries)
    pattern_ids = {p["id"] for p in cat["voice_patterns"]}
    assert not any(s == "voice_patterns" for s, _, _ in entries)
    fact = cat["persona_facts"][0]
    fact_text = next(t for s, i, t in entries if s == "persona_facts" and i == fact["id"])
    assert fact_text.endswith(fact["hecho"])
    assert pattern_ids  # sanity: the catalog has patterns that were skipped
    assert build_shadow_index_texts(None) == []


def test_logger_name_is_structured_shadow_logger():
    assert ps_mod.logger.name == "diana.cognitive.shadow"
    assert isinstance(ps_mod.logger, logging.Logger)


def test_module_does_not_import_outer_layers():
    tree = ast.parse(Path(ps_mod.__file__).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    allowed_stdlib = {"__future__", "asyncio", "logging", "math", "time", "dataclasses", "typing"}
    for module in modules:
        assert module in allowed_stdlib or module == "diana.cognitive.tags", module

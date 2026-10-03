"""feat/persona-operacion — alias-triggered internal business facts.

Conditions covered: optional top-level ``operacion`` key (legacy payloads,
empty list, restore), own tokenizer + whole-word n-gram matching (punctuation,
substrings, short/common aliases, persona_facts collisions), fenced
``knowledge.operacion`` block (cap, ``{hecho}`` only, Evaluator evidence),
deterministic Director trigger + trace, channel isolation, flag-off
byte-identical prompt, gray zone unchanged, panel CRUD.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest

from diana.application.gray_zone_proposal_service import (
    GrayZoneProposal,
    GrayZoneProposalService,
)
from diana.application.persona_admin_service import PersonaAdminService
from diana.application.persona_catalog_provider import PersonaCatalogProvider
from diana.cognitive.analyst import Analyst
from diana.cognitive.context_builder import EVALUATOR_KNOWLEDGE_BLOCKS, ContextBuilder
from diana.cognitive.decider import Decider
from diana.cognitive.director import CognitiveDirector
from diana.cognitive.evaluator import Evaluator
from diana.cognitive.generator import Generator
from diana.cognitive.models import Comprehension, EvaluationProfile, IncomingTurn
from diana.cognitive.operacion import (
    OPERACION_ALIAS_BLOCKLIST,
    alias_problem,
    match_operacion,
    validate_operacion_semantics,
    validate_operacion_structure,
)
from diana.cognitive.persona_catalog import (
    get_persona_atencion_catalog,
    get_persona_catalog,
    validate_persona_catalog,
)
from diana.cognitive.planner import Planner
from diana.cognitive.ports import InMemoryMessageHistory, InMemoryTraceStore
from diana.cognitive.registry import build_default_registry
from diana.cognitive.retrievers.operacion import OperacionRetriever
from diana.cognitive.tags import catalog_fact_topics, tokenize_words
from diana.config.settings import Settings
from diana.llm.deepseek import schema_hint_for_llm
from diana.llm.fake import FakeLLM
from diana.telegram.handlers.persona_admin import (
    _item_full_text,
    _section_items,
    apply_persona_edit,
)
from diana.telegram.keyboards import menu_personalidad_keyboard

LUCIEN = {
    "id": "lucien",
    "hecho": "Lucien es el bot administrador del canal VIP.",
    "alias": ["Lucien", "el mayordomo"],
    "nota_privada": "SECRETO-OPERACION",
}
CANAL = {
    "id": "canal_vip",
    "hecho": "El canal VIP se llama El Diván.",
    "alias": ["canal vip", "el divan"],
}


def _vip_catalog(items: list[dict] | None = None) -> dict:
    cat = deepcopy(get_persona_catalog())
    cat["operacion"] = deepcopy(items if items is not None else [LUCIEN, CANAL])
    return cat


def _atencion_catalog(items: list[dict] | None = None) -> dict:
    cat = deepcopy(get_persona_atencion_catalog())
    if items is not None:
        cat["operacion"] = deepcopy(items)
    return cat


def _turn(text: str, channel: str = "vip") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=7, text=text, channel_type=channel)  # type: ignore[arg-type]


def _comp(**overrides: Any) -> Comprehension:
    data: dict[str, Any] = {
        "intent": "otro", "topics": ["canal"], "emotion": "neutral", "urgency": "baja",
        "risk": "bajo", "needs_memory": False, "needs_policy": False,
        "needs_schedule": False, "needs_examples": False, "needs_history": False,
        "needs_context": False,
    }
    data.update(overrides)
    return Comprehension(**data)


def _profile() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9, precision=0.8, doctrine=0.85, consistency=0.9,
        safety=0.95, coverage=0.7, empathy=0.8,
    )


class _Provider:
    def __init__(self, by_channel: dict) -> None:
        self.by_channel = by_channel
        self.requested: list[str] = []

    async def get_catalog(self, channel_type: str = "vip"):
        self.requested.append(channel_type)
        return self.by_channel.get(channel_type)


def _director(provider: Any, *, enabled: bool, llm: FakeLLM, operacion_max: int = 2):
    history = InMemoryMessageHistory()
    trace = InMemoryTraceStore()
    director = CognitiveDirector(
        analyst=Analyst(llm),
        planner=Planner(),
        registry=build_default_registry(
            history, persona_catalog_provider=provider, operacion_max=operacion_max
        ),
        context_builder=ContextBuilder(),
        generator=Generator(llm),
        evaluator=Evaluator(llm),
        decider=Decider(),
        trace=trace,
        persona="P",
        history=history,
        persona_catalog_provider=provider,
        feature_persona_operacion_enabled=enabled,
    )
    return director, trace


def _llm() -> FakeLLM:
    return FakeLLM(structured_responses=[_comp(), _profile()], text_responses=["draft"])


# --- 1. payload contract ----------------------------------------------------


def test_legacy_payload_without_key_validates_and_is_not_mutated() -> None:
    legacy = deepcopy(get_persona_catalog())
    assert "operacion" not in legacy
    out = validate_persona_catalog(legacy)
    assert "operacion" not in out
    assert validate_operacion_structure(legacy) == []
    validate_operacion_semantics(legacy)  # no-op
    assert match_operacion(legacy, "¿Quién es Lucien?") == []


def test_empty_list_is_valid() -> None:
    cat = _vip_catalog([])
    assert validate_persona_catalog(cat)["operacion"] == []
    assert match_operacion(cat, "Lucien") == []


@pytest.mark.parametrize(
    ("bad", "msg"),
    [
        ("x", "must be a list"),
        (["x"], "must be an object"),
        ([{"id": "a", "hecho": "h"}], "missing alias"),
        ([{"id": "", "hecho": "h", "alias": ["lucien"]}], "non-empty string"),
        ([{"id": "a" * 25, "hecho": "h", "alias": ["lucien"]}], "24 bytes"),
        ([{"id": "a", "hecho": " ", "alias": ["lucien"]}], "hecho"),
        ([{"id": "a", "hecho": "h", "alias": []}], "non-empty list"),
        ([{"id": "a", "hecho": "h", "alias": ["lucien"]}] * 2, "duplicate id"),
    ],
)
def test_structure_validation(bad: Any, msg: str) -> None:
    cat = _vip_catalog()
    cat["operacion"] = bad
    with pytest.raises(ValueError, match=msg):
        validate_persona_catalog(cat)


def test_operacion_does_not_contaminate_persona_facts_paths() -> None:
    cat = _vip_catalog()
    temas = catalog_fact_topics(cat)
    assert "lucien" not in temas and "canal_vip" not in temas
    assert catalog_fact_topics(cat) == catalog_fact_topics(get_persona_catalog())


# --- 2. tokenizer + matching --------------------------------------------------


def test_tokenizer_strips_punctuation_accents_case() -> None:
    assert tokenize_words("¿Quién es Lucien?") == ["quien", "es", "lucien"]
    assert tokenize_words("¡¡LUCIEN!!") == ["lucien"]
    assert tokenize_words("canal-VIP, ya") == ["canal", "vip", "ya"]


@pytest.mark.parametrize(
    "text",
    ["¿Quién es Lucien?", "lucien", "¡Lucien!", "y el mayordomo?", "Me escribió LUCIEN."],
)
def test_alias_matches_with_punctuation_and_case(text: str) -> None:
    hits = match_operacion(_vip_catalog(), text)
    assert [h.id for h in hits] == ["lucien"]


@pytest.mark.parametrize(
    "text",
    [
        "Luciena me cae bien",  # alias as a substring of another word
        "lucienito",
        "el canal está lento",  # 'canal' alone is not the 'canal vip' bigram
        "soy vip",  # short / common word
        "el mayor domo",  # n-gram must be contiguous whole words
        "",
    ],
)
def test_no_false_positives(text: str) -> None:
    assert match_operacion(_vip_catalog(), text) == []


def test_multiword_alias_matches_and_ranking_cap() -> None:
    hits = match_operacion(_vip_catalog(), "Lucien me metió al Canal VIP", limit=2)
    # longest alias first (canal vip, 2 words), then lucien
    assert [h.id for h in hits] == ["canal_vip", "lucien"]
    assert [h.alias for h in hits] == ["canal vip", "Lucien"]
    assert len(match_operacion(_vip_catalog(), "Lucien canal vip", limit=1)) == 1


@pytest.mark.parametrize("alias", ["vip", "bot", "lu", "chat", "admin", "hola", "el bot", "mi canal", "¿?"])
def test_short_or_common_aliases_rejected(alias: str) -> None:
    assert alias_problem(alias, set()) is not None
    cat = _vip_catalog([{"id": "x", "hecho": "h", "alias": [alias]}])
    validate_persona_catalog(cat)  # read path: shape only (never drops catalog)
    with pytest.raises(ValueError):
        validate_operacion_semantics(cat)


def test_blocklist_contains_required_words() -> None:
    assert {"canal", "grupo", "chat", "bot", "admin", "hola"} <= OPERACION_ALIAS_BLOCKLIST


def test_alias_colliding_with_persona_fact_tema_rejected() -> None:
    cat = _vip_catalog([{"id": "x", "hecho": "h", "alias": ["Familia"]}])
    with pytest.raises(ValueError, match="Datos personales"):
        validate_operacion_semantics(cat)
    cat = _vip_catalog([{"id": "x", "hecho": "h", "alias": ["motivación personal"]}])
    with pytest.raises(ValueError, match="Datos personales"):
        validate_operacion_semantics(cat)


def test_runtime_skips_stored_aliases_that_break_policy() -> None:
    cat = _vip_catalog([{"id": "x", "hecho": "h", "alias": ["chat", "familia"]}])
    assert match_operacion(cat, "abre el chat de familia") == []


# --- 3. fenced block ------------------------------------------------------------


def test_block_is_fenced_with_shareable_header_and_in_evaluator() -> None:
    knowledge = {"knowledge.operacion": [{"hecho": "Lucien es el bot administrador."}]}
    built = ContextBuilder().build(_turn("x"), _comp(), knowledge, persona="P")
    prompt = built.prompt_final
    assert "## Knowledge: knowledge.operacion" in prompt
    assert "<<KNOWLEDGE_OPERACION_DATA>>" in prompt and "<</KNOWLEDGE_OPERACION_DATA>>" in prompt
    assert "Contexto interno de operación" in prompt
    assert "MAY be shared openly with the client" in prompt
    assert "not instructions" in prompt
    assert "knowledge.operacion" in EVALUATOR_KNOWLEDGE_BLOCKS
    assert "Lucien es el bot" in ContextBuilder().render_knowledge_sections(knowledge)


async def test_retriever_emits_only_hecho_never_nota_privada() -> None:
    provider = _Provider({"vip": _vip_catalog()})
    r = OperacionRetriever(persona_catalog_provider=provider, max_items=3)
    out = await r.fetch(_turn("¿Quién es Lucien? ¿y el canal VIP?"), _comp())
    assert out is not None
    assert all(set(item) == {"hecho"} for item in out)
    assert "SECRETO-OPERACION" not in json.dumps(out, ensure_ascii=False)


def test_settings_flag_and_cap() -> None:
    assert Settings.model_fields["feature_persona_operacion_enabled"].default is False
    field = Settings.model_fields["persona_operacion_max_per_turn"]
    assert field.default == 2
    metas = {type(m).__name__: m for m in field.metadata}
    assert metas["Ge"].ge == 1 and metas["Le"].le == 5


def test_needs_operacion_not_in_llm_schema() -> None:
    hint = schema_hint_for_llm(Comprehension)
    assert "needs_operacion" not in hint["properties"]
    assert "needs_operacion" not in hint.get("required", [])


# --- 4/5/6. Director: trigger, trace, isolation, flag off ---------------------


async def test_director_injects_and_traces_when_flag_on() -> None:
    provider = _Provider({"vip": _vip_catalog()})
    llm = _llm()
    director, trace = _director(provider, enabled=True, llm=llm)
    turn = _turn("¿Quién es Lucien?")
    await director.handle_turn(turn)

    comp = trace.get(turn.turn_id, "comprehension")
    assert comp["needs_operacion"] is True
    assert "knowledge.operacion" in trace.get(turn.turn_id, "plan")["capabilities"]
    match = trace.get(turn.turn_id, "operacion_match")
    assert match == {
        "channel_type": "vip",
        "matched": [{"id": "lucien", "alias": "Lucien"}],
        "injected_ids": ["lucien"],
        "injected": True,
    }
    prompt = trace.get(turn.turn_id, "prompt_text")
    assert "Lucien es el bot administrador del canal VIP." in prompt
    assert "SECRETO-OPERACION" not in prompt
    # Evaluator receives the evidence too (precision must not flag "Lucien").
    eval_call = [c for c in llm.calls if c[0] == "generate_structured"][1]
    assert "Lucien es el bot administrador" in eval_call[1]["messages"][-1]["content"]
    # Analyst never sees operacion material.
    analyst_call = next(c for c in llm.calls if c[0] == "generate_structured")
    assert "Lucien es el bot" not in json.dumps(analyst_call[1]["messages"], ensure_ascii=False)


async def test_director_no_match_no_trace_no_block() -> None:
    provider = _Provider({"vip": _vip_catalog()})
    director, trace = _director(provider, enabled=True, llm=_llm())
    turn = _turn("Luciena hola, ¿qué tal el canal?")
    await director.handle_turn(turn)
    assert trace.get(turn.turn_id, "operacion_match") is None
    assert "knowledge.operacion" not in trace.get(turn.turn_id, "prompt_text")


async def test_flag_off_prompt_byte_identical_to_legacy_catalog() -> None:
    text = "¿Quién es Lucien? te veo en el canal VIP"
    off_turn, legacy_turn = _turn(text), _turn(text)
    off_dir, off_trace = _director(_Provider({"vip": _vip_catalog()}), enabled=False, llm=_llm())
    legacy_dir, legacy_trace = _director(
        _Provider({"vip": deepcopy(get_persona_catalog())}), enabled=False, llm=_llm()
    )
    await off_dir.handle_turn(off_turn)
    await legacy_dir.handle_turn(legacy_turn)
    off_prompt = off_trace.get(off_turn.turn_id, "prompt_text")
    assert off_prompt == legacy_trace.get(legacy_turn.turn_id, "prompt_text")
    assert "operacion" not in off_prompt.lower()
    assert off_trace.get(off_turn.turn_id, "operacion_match") is None


async def test_flag_off_clears_stray_needs_operacion() -> None:
    llm = FakeLLM(
        structured_responses=[_comp(needs_operacion=True), _profile()],
        text_responses=["draft"],
    )
    director, trace = _director(_Provider({"vip": _vip_catalog()}), enabled=False, llm=llm)
    turn = _turn("Lucien")
    await director.handle_turn(turn)
    assert trace.get(turn.turn_id, "comprehension")["needs_operacion"] is False
    assert "knowledge.operacion" not in trace.get(turn.turn_id, "plan")["capabilities"]


async def test_atencion_never_uses_vip_operacion() -> None:
    provider = _Provider({"vip": _vip_catalog(), "atencion": _atencion_catalog()})
    director, trace = _director(provider, enabled=True, llm=_llm())
    turn = _turn("¿Quién es Lucien?", channel="atencion")
    await director.handle_turn(turn)
    assert trace.get(turn.turn_id, "operacion_match") is None
    assert "Lucien es el bot" not in trace.get(turn.turn_id, "prompt_text")
    assert set(provider.requested) == {"atencion"}


async def test_atencion_uses_its_own_operacion() -> None:
    own = [{"id": "lucien_atn", "hecho": "En atención te ayuda Lucien.", "alias": ["Lucien"]}]
    provider = _Provider({"vip": _vip_catalog(), "atencion": _atencion_catalog(own)})
    director, trace = _director(provider, enabled=True, llm=_llm())
    turn = _turn("¿Quién es Lucien?", channel="atencion")
    await director.handle_turn(turn)
    prompt = trace.get(turn.turn_id, "prompt_text")
    assert "En atención te ayuda Lucien." in prompt
    assert "bot administrador del canal VIP" not in prompt
    assert trace.get(turn.turn_id, "operacion_match")["injected_ids"] == ["lucien_atn"]


async def test_real_provider_static_fallbacks_have_no_operacion() -> None:
    class _Svc:
        async def get_current_persona(self, channel_type: str = "vip"):
            return None  # flag off / no active version → static files

    provider = PersonaCatalogProvider(_Svc())  # type: ignore[arg-type]
    r = OperacionRetriever(persona_catalog_provider=provider)
    assert await r.match(_turn("Lucien", "vip")) == []
    assert await r.match(_turn("Lucien", "atencion")) == []


async def test_cap_applies_in_director() -> None:
    provider = _Provider({"vip": _vip_catalog()})
    director, trace = _director(provider, enabled=True, llm=_llm(), operacion_max=1)
    turn = _turn("Lucien y el canal VIP")
    await director.handle_turn(turn)
    assert trace.get(turn.turn_id, "operacion_match")["injected_ids"] == ["canal_vip"]


# --- gray zone unchanged ---------------------------------------------------------


class _GZLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def generate_structured(self, messages, schema, **_):
        self.calls.append(list(messages))
        return GrayZoneProposal(proposed_rule="r", confidence=0.5)


async def test_gray_zone_payload_unchanged_by_operacion() -> None:
    with_op, without = _GZLLM(), _GZLLM()
    await GrayZoneProposalService(
        llm=with_op, persona_catalog_provider=_Provider({"vip": _vip_catalog()})
    ).generate(question="q", draft="d")
    await GrayZoneProposalService(
        llm=without, persona_catalog_provider=_Provider({"vip": deepcopy(get_persona_catalog())})
    ).generate(question="q", draft="d")
    assert with_op.calls[0] == without.calls[0]
    assert "Lucien" not in with_op.calls[0][1]["content"]


# --- 7. panel + restore ------------------------------------------------------------


def test_panel_add_edit_delete_including_last_item() -> None:
    base = deepcopy(get_persona_catalog())  # legacy: no operacion key
    added = apply_persona_edit(base, "operacion", None, "lucien | Lucien, el mayordomo | Lucien es el bot.")
    assert added["operacion"] == [
        {"id": "lucien", "alias": ["Lucien", "el mayordomo"], "hecho": "Lucien es el bot."}
    ]
    assert "operacion" not in base  # base not mutated
    edited = apply_persona_edit(added, "operacion", "lucien", "lucien | Lucien | Lucien administra el VIP.")
    assert edited["operacion"][0]["hecho"] == "Lucien administra el VIP."
    emptied = apply_persona_edit(edited, "operacion_del", "lucien", None)
    assert emptied["operacion"] == []  # last item CAN be deleted
    validate_persona_catalog(emptied)
    # required sections still keep the last-item guard
    single_fact = deepcopy(base)
    single_fact["persona_facts"] = single_fact["persona_facts"][:1]
    with pytest.raises(ValueError, match="último"):
        apply_persona_edit(single_fact, "fact_del", single_fact["persona_facts"][0]["id"], None)


@pytest.mark.parametrize(
    ("text", "msg"),
    [
        ("lucien | admin | hecho", "común"),
        ("lucien | vip | hecho", "corto"),
        ("lucien | familia | hecho", "Datos personales"),
        ("a" * 25 + " | Lucien | hecho", "24 bytes"),
        ("lucien | Lucien", "formato"),
        ("lucien |  | hecho", "vacíos"),
    ],
)
def test_panel_rejects_bad_input(text: str, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        apply_persona_edit(deepcopy(get_persona_catalog()), "operacion", None, text)


def test_panel_list_and_detail_render() -> None:
    cat = _vip_catalog()
    items = _section_items(cat, "operacion")
    assert [k for k, _ in items] == ["lucien", "canal_vip"]
    detail = _item_full_text(cat, "operacion", "lucien")
    assert detail is not None and "Alias: Lucien, el mayordomo" in detail
    assert _section_items(deepcopy(get_persona_catalog()), "operacion") == []


def test_keyboard_has_operacion_button() -> None:
    kb = menu_personalidad_keyboard()
    buttons = [b for row in kb.inline_keyboard for b in row]
    op = [b for b in buttons if b.text == "⚙️ Operación"]
    assert op and op[0].callback_data == "m:personalidad:operacion"


class _Store:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def list_versions(self, channel_type=None):
        return list(self.rows)

    async def insert_version(self, *, version, source, payload, created_by, channel_type):
        from types import SimpleNamespace

        rec = SimpleNamespace(id=uuid4(), version=version, payload=deepcopy(payload),
                              is_active=False, channel_type=channel_type)
        self.rows.append(rec)
        return rec

    async def activate_version(self, record_id, *, now, channel_type="vip"):
        found = None
        for r in self.rows:
            if r.channel_type == channel_type:
                r.is_active = r.id == record_id
                if r.is_active:
                    found = r
        return found

    async def get_active(self, *, channel_type="vip"):
        return next((r for r in self.rows if r.is_active and r.channel_type == channel_type), None)


async def test_restore_old_version_leaves_operacion_empty_and_save_enforces_policy() -> None:
    store = _Store()
    svc = PersonaAdminService(payload_store=store, feature_persona_admin_enabled=True, owner_telegram_id=1)
    old = await svc.save_persona(1, deepcopy(get_persona_catalog()))  # pre-feature version
    await svc.save_persona(1, _vip_catalog())
    assert (await svc.get_current_persona())["operacion"]
    await svc.restore(1, old.id)
    current = await svc.get_current_persona()
    assert "operacion" not in current
    assert match_operacion(current, "¿Quién es Lucien?") == []
    with pytest.raises(ValueError, match="común"):
        await svc.save_persona(1, _vip_catalog([{"id": "x", "hecho": "h", "alias": ["grupo"]}]))

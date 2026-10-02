"""hardener/persona-reglas ítem 1: Políticas y Patrones de voz llegan al modelo.

Mismo patrón que test_persona_facts_matching.py (commit 6507796):
normalización en ambos lados del cruce, guardado canónico en el panel,
vocabulario por canal para el Analyst y efecto en zona gris.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from diana.cognitive import analyst as analyst_mod
from diana.cognitive.decider import Decider
from diana.cognitive.models import (
    AnalystInput,
    Comprehension,
    EvaluationProfile,
    IncomingTurn,
)
from diana.cognitive.persona_catalog import (
    get_persona_atencion_catalog,
    get_persona_catalog,
)
from diana.cognitive.retrievers.policy import PolicyRetriever
from diana.cognitive.retrievers.voice_patterns import VoicePatternsRetriever
from diana.cognitive.tags import (
    catalog_fact_topics,
    catalog_pattern_tags,
    catalog_policy_topics,
    fair_share_limits,
    normalize_tag,
    normalize_tags,
)
from diana.telegram.handlers.persona_admin import (
    _parse_pattern,
    _parse_policy,
    apply_persona_edit,
)


def _turn(channel: str = "vip") -> IncomingTurn:
    return IncomingTurn(turn_id=uuid4(), chat_id=1, text="hola", channel_type=channel)  # type: ignore[arg-type]


def _comp(
    topics: list[str],
    *,
    intent: str = "otro",
    emotion: str = "neutral",
    needs_policy: bool = False,
    needs_voice: bool = False,
) -> Comprehension:
    return Comprehension(
        intent=intent,
        topics=topics,
        emotion=emotion,  # type: ignore[arg-type]
        urgency="baja",
        risk="bajo",
        needs_memory=False,
        needs_policy=needs_policy,
        needs_schedule=False,
        needs_examples=False,
        needs_history=False,
        needs_context=False,
        needs_voice_patterns=needs_voice,
    )


class _Provider:
    def __init__(self, by_channel: dict) -> None:
        self.by_channel = by_channel
        self.requested: list[str] = []

    async def get_catalog(self, channel_type: str = "vip"):
        self.requested.append(channel_type)
        return self.by_channel.get(channel_type)


# --- 1. normalización: idempotencia (llave de cruce para ítems 3 y 5) -------


@pytest.mark.parametrize(
    "raw",
    ["Precios especiales", "cariño", "extrañar", "precios/pagos", "Tema-pesado", "tono "],
)
def test_normalize_tag_is_idempotent(raw) -> None:
    once = normalize_tag(raw)
    assert normalize_tag(once) == once


# --- 2. panel: guardado canónico ------------------------------------------


def test_panel_parse_policy_stores_normalized_temas() -> None:
    item = _parse_policy("precios_esp | Precios especiales, Costos | No doy descuentos")
    assert item == {
        "id": "precios_esp",
        "tema": ["precios_especiales", "costos"],
        "regla": "No doy descuentos",
    }


def test_panel_parse_pattern_stores_normalized_tags() -> None:
    item = _parse_pattern("dificil | Tema pesado, Cariño | ay amor | Temas difíciles")
    assert item == {
        "id": "dificil",
        "tags": ["tema_pesado", "carino"],
        "patron": "ay amor",
        "uso": "Temas difíciles",
    }


@pytest.mark.parametrize(
    "text",
    ["p | - , __ | regla", "p | ‐ | regla"],
)
def test_panel_parse_policy_rejects_temas_that_normalize_to_empty(text) -> None:
    with pytest.raises(ValueError):
        _parse_policy(text)


def test_panel_parse_pattern_rejects_tags_that_normalize_to_empty() -> None:
    with pytest.raises(ValueError):
        _parse_pattern("p | - , __ | patron | uso")


def test_apply_persona_edit_policy_and_pattern_canonical() -> None:
    base = {"policies": [], "voice_patterns": []}
    out = apply_persona_edit(base, "policy", None, "p1 | Precios especiales | Regla")
    assert out["policies"][-1]["tema"] == ["precios_especiales"]
    out = apply_persona_edit(out, "pattern", None, "v1 | Tema pesado | patron | uso")
    assert out["voice_patterns"][-1]["tags"] == ["tema_pesado"]


# --- 3. lectura: legacy sin normalizar coincide (ambos lados) ---------------


async def test_policy_legacy_raw_tema_matches_normalized_topic() -> None:
    legacy = [{"id": "pe", "tema": ["Precios especiales"], "regla": "No hay descuentos."}]
    r = PolicyRetriever(static_policies=legacy)
    out = await r.fetch(_turn(), _comp(["precios_especiales"], needs_policy=True))
    assert out == ["Trigger: pe | Rule: No hay descuentos."]
    # Y al revés: el Analyst emite el tema con acento/espacios.
    out = await r.fetch(_turn(), _comp(["Precios Especiales"], needs_policy=True))
    assert out == ["Trigger: pe | Rule: No hay descuentos."]


async def test_policy_scalar_tema_and_intent_signal_normalized() -> None:
    r = PolicyRetriever(static_policies=[{"id": "x", "tema": "Pedir Consejo", "regla": "R"}])
    out = await r.fetch(_turn(), _comp([], intent="pedir_consejo"))
    assert out == ["Trigger: x | Rule: R"]


async def test_policy_no_match_still_returns_empty_list() -> None:
    r = PolicyRetriever(static_policies=[{"id": "x", "tema": ["precios"], "regla": "R"}])
    assert await r.fetch(_turn(), _comp(["", "  "], intent="")) == []


_VOICE = [
    {"id": "dificil", "tags": ["Tema pesado"], "patron": "ay amor", "uso": "U1"},
    {"id": "apodo", "tags": ["cariño"], "patron": "amor", "uso": "U2"},
]


async def test_voice_legacy_raw_tag_matches_normalized_topic() -> None:
    r = VoicePatternsRetriever(_VOICE)
    out = await r.fetch(_turn(), _comp(["tema_pesado"], needs_voice=True))
    assert out == {"patron": "ay amor", "uso": "U1"}


async def test_voice_accented_tag_matches_both_raw_and_normalized_signals() -> None:
    r = VoicePatternsRetriever(_VOICE)
    # topic normalizado que ahora ofrece el addendum
    assert await r.fetch(_turn(), _comp(["carino"])) == {"patron": "amor", "uso": "U2"}
    # topic crudo de la lista fija de _SYSTEM
    assert await r.fetch(_turn(), _comp(["cariño"])) == {"patron": "amor", "uso": "U2"}


async def test_voice_static_carinosa_tag_matches_emotion_enum() -> None:
    """R2: emoción ``cariñosa`` (enum crudo) ↔ tag ``cariñosa`` normalizado en ambos lados."""
    patterns = [{"id": "a", "tags": ["cariñosa"], "patron": "P", "uso": "U"}]
    r = VoicePatternsRetriever(patterns)
    assert await r.fetch(_turn(), _comp([], emotion="cariñosa")) == {"patron": "P", "uso": "U"}


async def test_voice_string_tags_do_not_crash() -> None:
    """R8: ``tags`` como string ya no cuenta caracteres ni divide entre cero."""
    r = VoicePatternsRetriever([{"id": "r", "tags": "risa", "patron": "jsjs", "uso": "U"}])
    assert await r.fetch(_turn(), _comp(["risa"])) == {"patron": "jsjs", "uso": "U"}


# --- 4. helpers de vocabulario: puros, sin tope por defecto, por tipo -------


def test_catalog_policy_topics_normalized_distinct_in_order() -> None:
    catalog = {
        "policies": [
            {"tema": ["Precios especiales", "costos"]},
            {"tema": "costos"},
            {"tema": ["Citas"]},
            "junk",
            {"regla": "sin tema"},
        ],
        "voice_patterns": [{"tags": ["risa"]}],
        "persona_facts": [{"tema": ["familia"]}],
    }
    assert catalog_policy_topics(catalog) == ["precios_especiales", "costos", "citas"]
    assert catalog_policy_topics(None) == []
    assert catalog_policy_topics({"policies": "bad"}) == []
    assert catalog_policy_topics({}) == []


def test_catalog_pattern_tags_normalized_distinct_in_order() -> None:
    catalog = {
        "voice_patterns": [
            {"tags": ["Tema pesado", "cariño"]},
            {"tags": "risa"},
            {"tags": ["cariño", "extrañar"]},
            42,
        ],
        "policies": [{"tema": ["precios"]}],
    }
    assert catalog_pattern_tags(catalog) == ["tema_pesado", "carino", "risa", "extranar"]
    assert catalog_pattern_tags(None) == []
    assert catalog_pattern_tags({"voice_patterns": {"x": 1}}) == []


def test_vocabulary_helpers_have_no_default_cap_but_accept_limit() -> None:
    many_pol = {"policies": [{"tema": [f"t{i}" for i in range(99)]}]}
    many_voz = {"voice_patterns": [{"tags": [f"g{i}" for i in range(99)]}]}
    assert len(catalog_policy_topics(many_pol)) == 99
    assert len(catalog_pattern_tags(many_voz)) == 99
    assert len(catalog_policy_topics(many_pol, limit=5)) == 5
    assert len(catalog_pattern_tags(many_voz, limit=5)) == 5
    # catalog_fact_topics conserva su firma/tope compatibles (limit=60).
    many_facts = {"persona_facts": [{"tema": [f"f{i}" for i in range(99)]}]}
    assert len(catalog_fact_topics(many_facts)) == 60
    assert len(catalog_fact_topics(many_facts, limit=None)) == 99


def test_vocabulary_helpers_are_separated_by_section() -> None:
    catalog = {
        "persona_facts": [{"tema": ["familia"]}],
        "policies": [{"tema": ["precios"]}],
        "voice_patterns": [{"tags": ["risa"]}],
    }
    assert catalog_fact_topics(catalog) == ["familia"]
    assert catalog_policy_topics(catalog) == ["precios"]
    assert catalog_pattern_tags(catalog) == ["risa"]


# --- 5. presupuesto justo por tipo (puro; reutilizable por ítems 3 y 5) -----


@pytest.mark.parametrize(
    ("sizes", "budget", "expected"),
    [
        # Todo cabe → nada se recorta (estáticos VIP 14/9/28 y atención 7/14/12).
        ([14, 9, 28], 60, [14, 9, 28]),
        ([7, 14, 12], 60, [7, 14, 12]),
        ([20, 20, 20], 60, [20, 20, 20]),
        # 60+ Datos: Políticas y Voz conservan su parte.
        ([70, 8, 28], 60, [26, 8, 26]),
        ([70, 8, 8], 60, [44, 8, 8]),
        ([100, 100, 100], 60, [20, 20, 20]),
        # Un solo tipo presente → todo el presupuesto.
        ([100, 0, 0], 60, [60, 0, 0]),
        ([0, 100, 0], 60, [0, 60, 0]),
        ([0, 0, 100], 60, [0, 0, 60]),
        # Sobrante indivisible → +1 a los primeros activos en orden de entrada.
        ([100, 7, 100], 60, [27, 7, 26]),
        ([100, 100, 100], 62, [21, 21, 20]),
        ([5, 5, 5], 2, [1, 1, 0]),
        # Ausentes / vacíos / presupuesto 0.
        ([0, 0, 0], 60, [0, 0, 0]),
        ([], 60, []),
        ([10, 10, 10], 0, [0, 0, 0]),
    ],
)
def test_fair_share_limits_cases(sizes, budget, expected) -> None:
    assert fair_share_limits(sizes, budget) == expected


def test_fair_share_limits_rejects_negative_budget() -> None:
    with pytest.raises(ValueError):
        fair_share_limits([1, 2, 3], -1)


def test_fair_share_limits_invariants_and_determinism() -> None:
    budget = 60
    for a in range(0, 75, 7):
        for b in range(0, 75, 11):
            for c in range(0, 75, 13):
                sizes = [a, b, c]
                limits = fair_share_limits(sizes, budget)
                assert limits == fair_share_limits(list(sizes), budget)  # determinista
                assert all(0 <= lim <= s for lim, s in zip(limits, sizes))
                assert sum(limits) == min(budget, sum(sizes))
                present = [s for s in sizes if s > 0]
                if present:
                    floor = budget // len(present)
                    for lim, s in zip(limits, sizes):
                        if s > 0:
                            assert lim >= min(s, floor), (sizes, limits)


# --- 5. addendum del Analyst: bloques por tipo, por canal, _SYSTEM intacto ---

# sha256 de analyst._SYSTEM en la base 947cc42: el ítem 1 NO lo edita.
_SYSTEM_SHA256_BASE = "4673ad282ea3bd47c7b62a2ae4ee3ab6bb7843a4b3130b3e427c6d0d46f4d368"


def _system_for(channel: str, catalog: dict) -> str:
    msgs = analyst_mod.Analyst(llm=None)._build_messages(  # type: ignore[arg-type]
        AnalystInput(
            turno_actual="hola",
            historial_reciente=[],
            channel_type=channel,  # type: ignore[arg-type]
            catalog_topics=catalog_fact_topics(catalog),
            policy_topics=catalog_policy_topics(catalog),
            voice_tags=catalog_pattern_tags(catalog),
        )
    )
    return msgs[0]["content"]


def _addendum(system: str) -> str:
    assert system.startswith(analyst_mod._SYSTEM)
    return system[len(analyst_mod._SYSTEM):]


def test_analyst_base_system_prompt_is_byte_identical_to_base() -> None:
    import hashlib

    digest = hashlib.sha256(analyst_mod._SYSTEM.encode("utf-8")).hexdigest()
    assert digest == _SYSTEM_SHA256_BASE
    # La lista fija conserva las formas crudas que consume el detector emocional.
    assert "extrañar" in analyst_mod._SYSTEM
    assert "cariño" in analyst_mod._SYSTEM


def test_addendum_without_policy_or_voice_is_unchanged() -> None:
    """Sin vocabulario nuevo el addendum es exactamente el de 6507796."""
    assert analyst_mod._catalog_addendum("vip", []) == ""
    assert analyst_mod._catalog_addendum("vip", [], [], []) == ""
    assert (
        analyst_mod._catalog_addendum("atencion", [], [], [])
        == analyst_mod._ATENCION_CHANNEL_GUIDANCE
    )
    assert analyst_mod._catalog_addendum("vip", ["mascota"], [], []) == (
        analyst_mod._catalog_addendum("vip", ["mascota"])
    )


def test_addendum_policy_and_voice_blocks_exact_text_vip() -> None:
    out = analyst_mod._catalog_addendum(
        "vip", ["mascota"], ["precios_especiales"], ["tema_pesado", "extranar"]
    )
    assert out == (
        " Active catalog temas (channel vip): mascota. These are ALSO valid topics: "
        "when the turn touches one of them, include that exact tema "
        "(verbatim, lowercase, with underscores) in topics and set "
        "needs_persona_facts=true if the turn asks about Diana's biography/personal facts."
        " Active policy temas (channel vip): precios_especiales. These are ALSO valid topics: "
        "when the turn touches one of them, include that exact tema "
        "(verbatim, lowercase, with underscores) in topics and set "
        "needs_policy=true."
        " Active voice pattern tags (channel vip): tema_pesado, extranar. These are ALSO valid topics: "
        "when the turn's register or subject matches one of them, include "
        "that exact tag (verbatim, lowercase, with underscores) in topics "
        "and set needs_voice_patterns=true."
    )


def test_addendum_atencion_overrides_vip_fixed_policy_list() -> None:
    out = analyst_mod._catalog_addendum("atencion", [], ["precios"], [])
    assert out.startswith(analyst_mod._ATENCION_CHANNEL_GUIDANCE)
    assert " Active policy temas (channel atencion): precios." in out
    assert (
        " In this channel these are the policy temas; the fixed 'Policy temas' "
        "list above belongs to the VIP channel and does not apply here."
    ) in out
    # VIP nunca recibe esa frase.
    assert "does not apply here" not in analyst_mod._catalog_addendum("vip", [], ["precios"], [])


def _listed(addendum: str, header: str) -> list[str]:
    """Terms of one addendum block, in prompt order ([] if the block is absent)."""
    marker = f" {header} (channel "
    if marker not in addendum:
        return []
    body = addendum.split(marker, 1)[1].split(": ", 1)[1].split(". These", 1)[0]
    return body.split(", ")


def _truncation_records(caplog) -> list:
    return [r for r in caplog.records if r.getMessage() == "analyst_catalog_vocab_truncated"]


def test_addendum_60_plus_facts_still_lists_policies_and_voice(caplog) -> None:
    facts = [f"f{i}" for i in range(70)]
    pols = [f"p{i}" for i in range(8)]
    voz = [f"v{i}" for i in range(28)]
    with caplog.at_level("WARNING", logger="diana.cognitive"):
        out = analyst_mod._catalog_addendum("vip", facts, pols, voz)
    # Reparto justo: 60 // 3 = 20; Políticas (8) cabe; quedan 52 → 26 + 26.
    assert _listed(out, "Active catalog temas") == facts[:26]
    assert _listed(out, "Active policy temas") == pols
    assert _listed(out, "Active voice pattern tags") == voz[:26]
    recs = _truncation_records(caplog)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.channel_type == "vip" and rec.max_terms == 60
    assert (rec.kept_fact_topics, rec.dropped_fact_topics) == (26, 44)
    assert (rec.kept_policy_topics, rec.dropped_policy_topics) == (8, 0)
    assert (rec.kept_voice_tags, rec.dropped_voice_tags) == (26, 2)
    assert rec.dropped == 46


def test_addendum_policies_never_crowded_out_by_facts_or_voice(caplog) -> None:
    facts = [f"f{i}" for i in range(200)]
    pols = [f"p{i}" for i in range(15)]
    voz = [f"v{i}" for i in range(200)]
    with caplog.at_level("WARNING", logger="diana.cognitive"):
        out = analyst_mod._catalog_addendum("atencion", facts, pols, voz)
    assert _listed(out, "Active policy temas") == pols  # 15 <= 20: completas
    assert len(_listed(out, "Active catalog temas")) == 23  # 45 // 2 = 22, +1 sobrante
    assert len(_listed(out, "Active voice pattern tags")) == 22
    assert "does not apply here" in out


@pytest.mark.parametrize(
    ("n_fact", "n_pol", "n_voz"),
    [(14, 9, 28), (7, 14, 12), (20, 20, 20), (60, 0, 0), (0, 0, 60), (1, 1, 58)],
)
def test_addendum_at_or_under_60_is_not_truncated(caplog, n_fact, n_pol, n_voz) -> None:
    facts = [f"f{i}" for i in range(n_fact)]
    pols = [f"p{i}" for i in range(n_pol)]
    voz = [f"v{i}" for i in range(n_voz)]
    with caplog.at_level("WARNING", logger="diana.cognitive"):
        out = analyst_mod._catalog_addendum("vip", facts, pols, voz)
    assert _listed(out, "Active catalog temas") == facts
    assert _listed(out, "Active policy temas") == pols
    assert _listed(out, "Active voice pattern tags") == voz
    assert not _truncation_records(caplog)


def test_addendum_budget_is_deterministic_and_keeps_catalog_order() -> None:
    facts = [f"f{i}" for i in range(90)]
    pols = [f"p{i}" for i in range(33)]
    voz = [f"v{i}" for i in range(41)]
    first = analyst_mod._catalog_addendum("vip", facts, pols, voz)
    for _ in range(5):
        assert analyst_mod._catalog_addendum("vip", list(facts), list(pols), list(voz)) == first
    # Cada bloque es un prefijo en orden de catálogo (nunca se reordena).
    assert _listed(first, "Active catalog temas") == facts[:20]
    assert _listed(first, "Active policy temas") == pols[:20]
    assert _listed(first, "Active voice pattern tags") == voz[:20]


@pytest.mark.parametrize(
    ("slot", "header"),
    [
        (0, "Active catalog temas"),
        (1, "Active policy temas"),
        (2, "Active voice pattern tags"),
    ],
)
def test_addendum_single_type_present_gets_full_budget(caplog, slot, header) -> None:
    terms = [f"t{i}" for i in range(75)]
    groups: list[list[str]] = [[], [], []]
    groups[slot] = terms
    with caplog.at_level("WARNING", logger="diana.cognitive"):
        out = analyst_mod._catalog_addendum("vip", *groups)
    assert _listed(out, header) == terms[:60]
    rec = _truncation_records(caplog)[0]
    assert rec.dropped == 15


def test_static_catalogs_fit_under_cap() -> None:
    for cat in (get_persona_catalog(), get_persona_atencion_catalog()):
        total = (
            len(catalog_fact_topics(cat))
            + len(catalog_policy_topics(cat))
            + len(catalog_pattern_tags(cat))
        )
        assert total <= analyst_mod._MAX_CATALOG_TOPICS_IN_PROMPT, total


def test_addendum_channel_isolation_vip_vs_atencion() -> None:
    vip = _addendum(_system_for("vip", get_persona_catalog()))
    at = _addendum(_system_for("atencion", get_persona_atencion_catalog()))
    # VIP-exclusivos nunca en atención (el _SYSTEM fijo se excluye al comparar).
    for vip_only in ("dinamica_novia_virtual", "momento_bonito", "extranar", "psicologia"):
        assert vip_only in vip, vip_only
        assert vip_only not in at, vip_only
    # Atención-exclusivos nunca en VIP.
    for at_only in ("precios", "citas", "despedida", "redireccion"):
        assert at_only in at, at_only
        assert at_only not in vip, at_only


@pytest.mark.parametrize(
    ("channel", "loader"),
    [("vip", get_persona_catalog), ("atencion", get_persona_atencion_catalog)],
)
def test_every_static_policy_and_voice_pattern_is_reachable(channel, loader) -> None:
    """Cobertura DoD 4: 100 % de las reglas estáticas tienen ≥1 tema/tag en el addendum."""
    cat = loader()
    add = _addendum(_system_for(channel, cat))
    pol_line = add.split(" Active policy temas (channel ")[1].split(". These")[0]
    voz_line = add.split(" Active voice pattern tags (channel ")[1].split(". These")[0]
    pol_vocab = set(pol_line.split(": ", 1)[1].split(", "))
    voz_vocab = set(voz_line.split(": ", 1)[1].split(", "))
    for pol in cat["policies"]:
        assert set(normalize_tags(pol.get("tema"))) & pol_vocab, pol["id"]
    for pat in cat["voice_patterns"]:
        assert set(normalize_tags(pat.get("tags"))) & voz_vocab, pat["id"]


# --- 6. zona gris: tema de política de atención antes inalcanzable ----------


def _profile() -> EvaluationProfile:
    return EvaluationProfile(
        naturalness=0.9,
        precision=0.8,
        doctrine=0.85,
        consistency=0.9,
        safety=0.9,
        coverage=0.7,
        empathy=0.8,
    )


@pytest.mark.parametrize("tema", ["precios", "costos", "citas", "contacto", "alcance"])
async def test_atencion_policy_tema_now_offered_and_avoids_doctrine_not_found(tema) -> None:
    at = get_persona_atencion_catalog()
    # Antes: el tema no estaba en ningún vocabulario del prompt de atención.
    assert tema not in analyst_mod._SYSTEM
    assert tema not in catalog_fact_topics(at)
    # Ahora: el addendum de atención lo ofrece como topic válido.
    assert tema in _addendum(_system_for("atencion", at))
    provider = _Provider({"atencion": at})
    retriever = PolicyRetriever(persona_catalog_provider=provider)  # type: ignore[arg-type]
    comp = _comp([tema], needs_policy=True)
    policies = await retriever.fetch(_turn("atencion"), comp)
    assert policies, tema
    assert provider.requested == ["atencion"]
    decision = Decider(feature_gray_zone_enabled=True).decide(
        _profile(), comp, retrieved={"knowledge.policy": policies}
    )
    assert decision.reason != "doctrine_not_found"
    assert decision.action != "consult_doctrine"
    # Control: sin política recuperada sí sería zona gris.
    gray = Decider(feature_gray_zone_enabled=True).decide(
        _profile(), comp, retrieved={"knowledge.policy": []}
    )
    assert gray.reason == "doctrine_not_found"


# --- 7. gaps de TESTS.md (paso 2.5b): G1 log en atención, G2 tamaños negativos ---


def test_addendum_truncation_log_atencion_channel_level_and_logger(caplog) -> None:
    """G1: el log de recorte identifica el canal real (no "vip" fijo) y usa el
    logger exacto ``diana.cognitive`` con nivel WARNING."""
    import logging

    facts = [f"f{i}" for i in range(70)]
    with caplog.at_level("WARNING", logger="diana.cognitive"):
        analyst_mod._catalog_addendum("atencion", facts, ["p0"], [])
    recs = _truncation_records(caplog)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.channel_type == "atencion"
    assert rec.levelno == logging.WARNING
    assert rec.name == "diana.cognitive"
    assert rec.max_terms == 60
    # Reparto justo [70, 1, 0] → Políticas (1) cabe; Datos recibe el resto (59).
    assert (rec.kept_fact_topics, rec.dropped_fact_topics) == (59, 11)
    assert (rec.kept_policy_topics, rec.dropped_policy_topics) == (1, 0)
    assert (rec.kept_voice_tags, rec.dropped_voice_tags) == (0, 0)
    assert rec.dropped == 11


def test_fair_share_limits_treats_negative_sizes_as_absent() -> None:
    """G2: tamaños negativos cuentan como ausentes (0) y no consumen presupuesto."""
    assert fair_share_limits([-5, 10, 70], 60) == [0, 10, 50]

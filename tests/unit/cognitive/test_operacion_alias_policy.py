"""Operación: política de alias (ítem 2 persona-reglas).

B1 núcleo del alias (artículos opcionales en los bordes), B3 política sobre el
núcleo, B5 nombres propios de 3 letras (y falsos positivos Sol/Mar/Leo), B6
ranking bajo el tope, B7 ``alias_issues`` y G2 (al guardar solo se valida lo
nuevo). Funciones puras de ``diana.cognitive.operacion``.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

import pytest

from diana.cognitive.operacion import (
    OPERACION_ALIAS_SHORT_BLOCKLIST,
    AliasIssue,
    alias_core,
    alias_issues,
    alias_problem,
    fact_temas,
    match_operacion,
    validate_operacion_semantics,
)
from diana.cognitive.persona_catalog import (
    get_persona_atencion_catalog,
    get_persona_catalog,
)
from diana.cognitive.tags import catalog_fact_topics

LUCIEN = {
    "id": "lucien",
    "hecho": "Lucien es el bot administrador del canal VIP.",
    "alias": ["Lucien", "el mayordomo"],
}
DIVAN = {"id": "divan", "hecho": "El canal VIP se llama El Diván.", "alias": ["El Diván"]}
CANAL = {"id": "canal_vip", "hecho": "El canal VIP es de pago.", "alias": ["canal vip"]}


def _cat(items: list[dict], base: dict | None = None) -> dict:
    cat = deepcopy(base if base is not None else get_persona_catalog())
    cat["operacion"] = deepcopy(items)
    return cat


def _item(item_id: str, *aliases: str) -> dict:
    return {"id": item_id, "hecho": f"Hecho de {item_id}.", "alias": list(aliases)}


# --- B1: núcleo del alias -------------------------------------------------------


@pytest.mark.parametrize(
    ("alias", "core"),
    [
        ("El Diván", ("divan",)),
        ("el mayordomo", ("mayordomo",)),
        ("el canal de ventas", ("canal", "de", "ventas")),  # internos se conservan
        ("¿Lucien?", ("lucien",)),
        ("tu diván, ya", ("divan",)),
        ("de la", ()),
        ("", ()),
    ],
)
def test_alias_core_strips_edge_function_words_only(alias: str, core: tuple) -> None:
    assert alias_core(alias) == core


@pytest.mark.parametrize("text", ["diván", "¿Y tu diván?", "Entré al divan", "EL DIVÁN"])
def test_article_is_optional_in_the_text(text: str) -> None:
    hits = match_operacion(_cat([DIVAN]), text)
    assert [(h.id, h.alias) for h in hits] == [("divan", "El Diván")]  # alias original


def test_mayordomo_without_article_and_no_new_false_positives() -> None:
    cat = _cat([LUCIEN])
    hits = match_operacion(cat, "¿y tu mayordomo?")
    assert [(h.id, h.alias) for h in hits] == [("lucien", "el mayordomo")]
    assert match_operacion(cat, "Luciena me cae bien") == []
    assert match_operacion(cat, "lucienito") == []
    assert match_operacion(cat, "el mayor domo") == []


def test_inner_function_words_are_kept() -> None:
    cat = _cat([_item("ventas", "el canal de ventas")])
    assert [h.id for h in match_operacion(cat, "¿Cuál es el canal de ventas?")] == ["ventas"]
    assert match_operacion(cat, "canal ventas") == []


# --- B3: política y choque sobre el núcleo ---------------------------------------


@pytest.mark.parametrize(
    ("alias", "msg"),
    [("el bot", "corto"), ("el chat", "común"), ("mi canal", "común"), ("de la", "común")],
)
def test_policy_runs_on_the_core(alias: str, msg: str) -> None:
    problem = alias_problem(alias, set())
    assert problem is not None and msg in problem


def test_collision_with_datos_personales_runs_on_the_core() -> None:
    temas = fact_temas(get_persona_catalog())
    assert "familia" in temas
    for alias in ("Familia", "mi familia", "la familia de"):
        problem = alias_problem(alias, temas)
        assert problem is not None and "Datos personales" in problem
    with pytest.raises(ValueError, match="Datos personales"):
        validate_operacion_semantics(_cat([_item("x", "mi familia")]))
    # "el canal de ventas" no choca con el tema "canal": núcleo de 3 palabras.
    assert alias_problem("el canal de ventas", temas) is None


def test_collision_universe_is_the_item1_helper_uncapped() -> None:
    cat = deepcopy(get_persona_catalog())
    cat["persona_facts"] = list(cat["persona_facts"]) + [
        {"id": f"t{i}", "tema": [f"Tema {i}"], "hecho": "h"} for i in range(70)
    ]
    assert fact_temas(cat) == set(catalog_fact_topics(cat, limit=None))
    assert len(catalog_fact_topics(cat)) == 60  # el default sí recorta…
    problem = alias_problem("el tema 69", fact_temas(cat))  # …la colisión no
    assert problem is not None and "Datos personales" in problem


# --- B5: nombres propios de 3 letras y falsos positivos -------------------------


@pytest.mark.parametrize("alias", ["Ana", "Max", "¿Eva?", "la Ana", "ANA"])
def test_capitalized_three_letter_proper_name_accepted(alias: str) -> None:
    assert alias_problem(alias, set()) is None


@pytest.mark.parametrize(
    ("alias", "msg"),
    [
        ("ana", "corto"),  # sin mayúscula no es nombre propio
        ("Lu", "corto"),
        ("lu", "corto"),
        ("X", "corto"),
        ("Sol", "común"),
        ("Mar", "común"),
        ("Leo", "común"),
        ("Vip", "común"),
        ("Bot", "común"),
        ("Hoy", "común"),
    ],
)
def test_short_aliases_rejected(alias: str, msg: str) -> None:
    problem = alias_problem(alias, set())
    assert problem is not None and msg in problem


def test_short_blocklist_covers_names_that_are_common_words() -> None:
    assert {"sol", "mar", "leo", "luz", "paz", "rey", "oro"} <= OPERACION_ALIAS_SHORT_BLOCKLIST
    assert not {"ana", "max", "eva"} & OPERACION_ALIAS_SHORT_BLOCKLIST


@pytest.mark.parametrize(
    "text", ["hace sol hoy", "me encanta el mar", "leo un libro", "¿Leo?", "Sol y Mar"]
)
def test_stored_short_common_aliases_never_fire(text: str) -> None:
    # Guardados antes de la regla (legacy): al leer se ignoran, no disparan.
    cat = _cat([_item("sol", "Sol"), _item("mar", "Mar"), _item("leo", "Leo")])
    assert match_operacion(cat, text) == []


def test_proper_name_matches_lowercase_text_but_not_inside_words() -> None:
    cat = _cat([_item("ana", "Ana")])
    assert [h.id for h in match_operacion(cat, "¿quién es ana?")] == ["ana"]
    assert match_operacion(cat, "ananá") == []
    assert match_operacion(_cat([_item("ana", "ana")]), "ana") == []  # guardado en minúscula


# --- B6: ranking bajo el tope -----------------------------------------------------


def test_ranking_by_core_letters_lets_lucien_in_under_the_cap() -> None:
    cat = _cat([DIVAN, LUCIEN, CANAL])
    text = "canal vip y lucien y el divan"
    # letras del núcleo: canalvip 8 > lucien 6 > divan 5
    assert [h.id for h in match_operacion(cat, text, limit=2)] == ["canal_vip", "lucien"]
    assert [h.id for h in match_operacion(cat, text, limit=3)] == ["canal_vip", "lucien", "divan"]


def test_ranking_ties_more_words_then_catalog_order() -> None:
    cat = _cat([_item("b", "Gutierre"), _item("c", "Gutierra"), _item("a", "casa azul")])
    hits = match_operacion(cat, "Gutierra, Gutierre y la casa azul", limit=3)
    # 8 letras las tres: 2 palabras primero; empate b/c → orden del catálogo
    assert [h.id for h in hits] == ["a", "b", "c"]


def test_best_alias_of_an_item_is_the_most_specific() -> None:
    hits = match_operacion(_cat([LUCIEN]), "Lucien, el mayordomo")
    assert [(h.id, h.alias) for h in hits] == [("lucien", "el mayordomo")]


# --- B7: alias que Diana no usa ------------------------------------------------------


def test_alias_issues_lists_exactly_the_aliases_the_matcher_ignores() -> None:
    cat = _cat([_item("lucien", "Lucien", "mi familia", "Sol"), _item("ok", "canal vip")])
    issues = alias_issues(cat)
    assert all(isinstance(i, AliasIssue) for i in issues)
    assert [(i.id, i.alias) for i in issues] == [("lucien", "mi familia"), ("lucien", "Sol")]
    assert "Datos personales" in issues[0].reason
    assert "común" in issues[1].reason
    assert match_operacion(cat, "mi familia y el sol") == []
    assert [h.id for h in match_operacion(cat, "Lucien")] == ["lucien"]


@pytest.mark.parametrize(
    "bad",
    [None, {}, {"operacion": "x"}, {"operacion": [1, {"id": "x"}, {"id": "y", "alias": "Sol"}]}],
)
def test_alias_issues_is_shape_tolerant(bad: object) -> None:
    assert alias_issues(bad) == []  # type: ignore[arg-type]


def test_alias_issues_uses_the_given_channel_catalog_only() -> None:
    items = [_item("x", "mi familia", "mi negocio")]
    vip = alias_issues(_cat(items))
    atn = alias_issues(_cat(items, base=get_persona_atencion_catalog()))
    assert [i.alias for i in vip] == ["mi familia"]  # "familia" es tema de VIP
    assert [i.alias for i in atn] == ["mi negocio"]  # "negocio" es tema de atención


# --- G2: al guardar solo se valida lo nuevo ------------------------------------------


def test_previous_version_aliases_never_block() -> None:
    legacy = _cat([_item("lucien", "Lucien", "mi familia")])
    with pytest.raises(ValueError, match="Datos personales"):
        validate_operacion_semantics(legacy)  # sin previous → todo
    validate_operacion_semantics(legacy, previous=legacy)  # nada nuevo
    edited = deepcopy(legacy)
    edited["operacion"][0]["hecho"] = "Lucien administra el VIP."
    validate_operacion_semantics(edited, previous=legacy)  # solo cambió el hecho


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["operacion"][0]["alias"].append("Sol"),  # alias nuevo en ítem editado
        lambda c: c["operacion"].append(_item("otro", "mi familia")),  # ítem nuevo
        lambda c: c["operacion"][0].update(id="lucien2"),  # renombrado = ítem nuevo
    ],
)
def test_new_or_edited_aliases_are_validated(mutate: Callable[[dict], object]) -> None:
    legacy = _cat([_item("lucien", "Lucien", "mi familia")])
    nuevo = deepcopy(legacy)
    mutate(nuevo)
    with pytest.raises(ValueError):
        validate_operacion_semantics(nuevo, previous=legacy)


def test_previous_of_another_channel_is_not_a_whitelist() -> None:
    # El servicio pasa la versión activa DEL MISMO canal; atención sin
    # operación previa valida todo aunque VIP tenga ese alias guardado.
    vip_prev = _cat([_item("lucien", "Lucien", "Sol")])
    atn_new = _cat([_item("lucien", "Lucien", "Sol")], base=get_persona_atencion_catalog())
    validate_operacion_semantics(vip_prev, previous=vip_prev)
    with pytest.raises(ValueError, match="común"):
        validate_operacion_semantics(atn_new, previous=get_persona_atencion_catalog())

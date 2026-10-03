"""PersonaRuleDrafter — plain text → one panel item (hardener/persona-reglas ítem 3, C2)."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from diana.application.persona_rule_drafter import (
    DEFAULT_DRAFT_TIMEOUT_SECONDS,
    DRAFT_OPS,
    PersonaRuleDrafter,
    fallback_draft,
)
from diana.cognitive.persona_catalog import load_persona_catalog
from diana.llm.fake import FakeLLM
from diana.telegram.handlers.persona_admin import apply_persona_edit

SECRET = "SECRETO-NOTA-123"


def _catalog() -> dict:
    cat = deepcopy(load_persona_catalog())
    cat["persona_facts"][0]["nota_privada"] = SECRET
    return cat


async def test_llm_draft_for_fact_is_postprocessed():
    llm = FakeLLM(structured_responses=[{"id": "Mi Perro Toby!!", "temas": ["Mascotas"],
                                         "hecho": "Tengo un perro, Toby."}])
    d = await PersonaRuleDrafter(llm).draft("fact", "tengo un perro que se llama Toby", catalog=_catalog())
    assert d.source == "llm"
    assert d.item == {"id": "mi_perro_toby", "tema": ["mascotas"], "hecho": "Tengo un perro, Toby."}


async def test_nota_privada_never_reaches_the_llm_even_when_editing():
    cat = _catalog()
    target = cat["persona_facts"][0]["id"]
    llm = FakeLLM(structured_responses=[{"id": target, "temas": ["familia"], "hecho": "h"}])
    await PersonaRuleDrafter(llm).draft("fact", "cambia esto", catalog=cat, target=target)
    sent = json.dumps(llm.calls[0][1]["messages"], ensure_ascii=False)
    assert SECRET not in sent and "nota_privada" not in sent


async def test_context_has_vocabulary_and_ids_but_no_other_hechos():
    cat = _catalog()
    llm = FakeLLM(structured_responses=[{"id": "x", "temas": ["t"], "hecho": "h"}])
    await PersonaRuleDrafter(llm).draft("fact", "algo", catalog=cat)
    content = llm.calls[0][1]["messages"][-1]["content"]
    assert set(json.loads(content)) == {"seccion", "texto_del_owner", "vocabulario",
                                        "ids_existentes", "elemento_actual"}
    assert cat["persona_facts"][1]["hecho"] not in content


async def test_timeout_falls_back_deterministically():
    class _Slow:
        async def generate_structured(self, *a, **k):
            await asyncio.sleep(1)

    d = await PersonaRuleDrafter(_Slow(), timeout=0.01).draft(
        "policy", "Nunca hablo de mi ex", catalog=_catalog())
    assert d.source == "fallback" and d.item["regla"] == "Nunca hablo de mi ex"


def test_default_timeout_is_10_seconds():
    assert PersonaRuleDrafter(None)._timeout == 10.0 == DEFAULT_DRAFT_TIMEOUT_SECONDS  # noqa: SLF001


async def test_llm_exception_falls_back():
    d = await PersonaRuleDrafter(FakeLLM()).draft("policy", "Nunca hablo de mi ex", catalog=_catalog())
    assert d.source == "fallback"


async def test_invalid_llm_shape_falls_back():
    # Review round 1 (S2): extra keys are now dropped, so "invalid" = wrong type.
    llm = FakeLLM(structured_responses=[{"id": "x", "temas": {"no": "lista"}, "regla": "r"}])
    d = await PersonaRuleDrafter(llm).draft("policy", "Nunca hablo de mi ex", catalog=_catalog())
    assert d.source == "fallback"


async def test_llm_reply_with_nota_privada_is_dropped_and_never_logged(caplog):
    """S2: a hallucinated ``nota_privada`` key never reaches the item or the logs."""
    caplog.set_level("DEBUG")
    llm = FakeLLM(structured_responses=[
        {"id": "x", "temas": ["familia"], "hecho": "Tengo un hermano.", "nota_privada": SECRET}
    ])
    d = await PersonaRuleDrafter(llm).draft("fact", "Tengo un hermano.", catalog=_catalog())
    assert d.source == "llm"
    assert "nota_privada" not in d.item
    assert SECRET not in json.dumps(d.item, ensure_ascii=False)
    assert SECRET not in caplog.text


async def test_draft_failure_logs_error_type_only(caplog):
    """S2: the provider error text (may echo the owner text) is never logged."""

    class _Boom:
        async def generate_structured(self, *a, **k):
            raise ValueError(f"1 validation error input_value='{SECRET}'")

    caplog.set_level("DEBUG")
    d = await PersonaRuleDrafter(_Boom()).draft("policy", "Nunca hablo de mi ex", catalog=_catalog())
    assert d.source == "fallback"
    records = [r for r in caplog.records if r.getMessage() == "persona_rule_draft_failed"]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert records[0].exc_info is None
    assert records[0].error == "ValueError"
    assert SECRET not in caplog.text


async def test_no_llm_uses_fallback():
    d = await PersonaRuleDrafter(None).draft("policy", "Nunca hablo de mi ex", catalog=_catalog())
    assert d.source == "fallback"
    assert d.item["regla"] == "Nunca hablo de mi ex"


async def test_edit_keeps_target_id():
    cat = _catalog()
    cat["persona_facts"].append({"id": "mama", "tema": ["familia"], "hecho": "Mi mamá."})
    llm = FakeLLM(structured_responses=[{"id": "otro_id", "temas": ["familia"], "hecho": "h"}])
    d = await PersonaRuleDrafter(llm).draft("fact", "mi mamá", catalog=cat, target="mama")
    assert d.item["id"] == "mama"


async def test_new_id_is_unique_with_suffix():
    cat = _catalog()
    existing = cat["policies"][0]["id"]
    llm = FakeLLM(structured_responses=[{"id": existing, "temas": ["t"], "regla": "r"}])
    d = await PersonaRuleDrafter(llm).draft("policy", "algo", catalog=cat)
    assert d.item["id"] == f"{existing}_2"


async def test_id_capped_to_24_bytes():
    llm = FakeLLM(structured_responses=[{
        "id": "una regla con un nombre larguisimo de verdad", "temas": ["t"], "regla": "r",
    }])
    d = await PersonaRuleDrafter(llm).draft("policy", "algo", catalog=_catalog())
    assert len(d.item["id"].encode("utf-8")) <= 24
    assert not d.item["id"].endswith("_")


async def test_operacion_aliases_filtered_by_policy_and_deduped_by_core():
    llm = FakeLLM(structured_responses=[{
        "id": "divan", "alias": ["El Diván", "diván", "bot", "familia"],
        "hecho": "El canal VIP se llama El Diván.",
    }])
    d = await PersonaRuleDrafter(llm).draft("operacion", "el canal vip es El Diván", catalog=_catalog())
    assert d.source == "llm"
    assert d.item["alias"] == ["El Diván"]


def test_operacion_without_valid_alias_raises_in_fallback():
    with pytest.raises(ValueError, match="id | alias1"):
        fallback_draft("operacion", "esto no tiene ningun nombre claro", catalog=_catalog())


def test_fallback_fact_picks_vocabulary_temas():
    cat = _catalog()
    tema = cat["persona_facts"][0]["tema"][0]
    item = fallback_draft("fact", f"algo sobre {tema} y más", catalog=cat)
    assert tema in item["tema"]
    assert item["hecho"] == f"algo sobre {tema} y más"


def test_fallback_fact_without_vocab_uses_longest_word():
    item = fallback_draft("fact", "tengo un perro chihuahua", catalog={"persona_facts": []})
    assert item["tema"] == ["chihuahua"]


def test_fallback_bloque_parses_days_and_times():
    item = fallback_draft("bloque", "lunes y miércoles de 9:00 a 13:00 gimnasio", catalog=_catalog())
    assert item["dias"] == ["lunes", "miercoles"]
    # Zero-padded: the catalog validator requires HH:MM (persona_catalog._HHMM_RE).
    assert item["inicio"] == "09:00"
    assert item["fin"] == "13:00"
    assert "gimnasio" in item["actividad"]


def test_fallback_bloque_without_times_raises():
    with pytest.raises(ValueError, match="dias | inicio | fin | actividad"):
        fallback_draft("bloque", "los lunes voy al gimnasio", catalog=_catalog())


def test_drafter_output_matches_pipe_parser_shape():
    cat = _catalog()
    pipe = {
        "fact": ("persona_facts", "zz_fact | t1 | hecho", None),
        "policy": ("policies", "zz_pol | t1 | regla", None),
        "pattern": ("voice_patterns", "zz_pat | t1 | patron | uso", None),
        "operacion": ("operacion", "zz_op | Lucien | hecho", None),
        "bloque": ("bloques", "lunes | 09:00 | 10:00 | algo", None),
    }
    texts = {
        "fact": "tengo un perro",
        "policy": "nunca hablo de mi ex",
        "pattern": "digo mi vida al despedirme",
        "operacion": "El mayordomo se llama Lucien",
        "bloque": "lunes de 9:00 a 10:00 gimnasio",
    }
    assert set(DRAFT_OPS) == set(pipe)
    for op, (section, text, extra) in pipe.items():
        edited = apply_persona_edit(cat, op, extra, text)
        if section == "bloques":
            expected = edited["schedule"]["bloques"][-1]
        else:
            expected = edited[section][-1]
        drafted = fallback_draft(op, texts[op], catalog=cat)
        assert set(drafted) == set(expected), op

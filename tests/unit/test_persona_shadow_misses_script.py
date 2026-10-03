"""scripts/persona_shadow_misses.py — read-only query over the shadow log (review round 1, P2)."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from diana.application.logformat import ColorExtraFormatter

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "persona_shadow_misses.py"


def _load():
    spec = importlib.util.spec_from_file_location("persona_shadow_misses", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod  # dataclasses resolve the module by name
    spec.loader.exec_module(mod)
    return mod


def _line(event: str, **extra) -> str:
    record = logging.LogRecord("diana.cognitive", logging.INFO, __file__, 1, event, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return ColorExtraFormatter().format(record)


def test_lists_only_semantic_hits_the_deterministic_match_missed():
    mod = _load()
    top = [
        {"section": "policies", "id": "precios", "score": 0.81},
        {"section": "persona_facts", "id": "familia_hermana", "score": 0.42},
        {"section": "operacion", "id": "lucien", "score": 0.3},
    ]
    lines = [
        _line("persona_semantic_shadow", turn_id="t-1", channel_type="atencion",
              model_name="m", top=top, already_retrieved=[True, False, False],
              index_size=10, embed_ms=11.0, elapsed_ms=12.0),
        _line("persona_semantic_shadow_dropped", turn_id="t-2", channel_type="vip"),
        "basura sin formato",
    ]
    misses = mod.parse_misses(lines)
    assert [(m.turn_id, m.channel_type, m.section, m.item_id) for m in misses] == [
        ("t-1", "atencion", "persona_facts", "familia_hermana"),
        ("t-1", "atencion", "operacion", "lucien"),
    ]
    assert [m.item_id for m in mod.parse_misses(lines, min_score=0.4)] == ["familia_hermana"]

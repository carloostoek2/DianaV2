"""scripts/vigilantes.py — modo seco del vigilante y la voz de la copia que lee la duena.

El chequeo de verdad corre dentro del bot; este script existe para mirarlo a mano sin esperar
la corrida del dia y sin mandar nada. Lo que se prueba aca es que el modo seco no tenga efecto,
que el aviso de puesta en marcha salga una sola vez y que la copia al usuario siga en espanol
neutro (el aviso se escribio a mano y se habia desviado de la copia que manda el sistema).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from diana.application.contract_watchdog_service import leer_vigilantes

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vigilantes.py"

# Voseo (presente e imperativo). La copia de producto usa espanol neutro: "tu", nunca "vos".
# Un acierto aca significa que el texto que lee la duena se contagio de una forma regional.
_VOSEO = re.compile(
    r"\b(tenés|podés|querés|sabés|sos|hacés|ponés|decís|venís|salís|andás|dejás|"
    r"mandás|pasás|hablás|pensás|mirás|escuchás|escribís|vivís|sentís|preferís|"
    r"elegís|seguís|pedís|permitís|decidís|corregís|aprobás|escalás|confirmás|"
    r"aceptás|rechazás|tocás|apretás|usás|necesitás|esperás|notás|revisás|sumás|"
    r"sacás|abrís|cerrás|tomás|buscás|andá|fijate|fijáte|mirá|decime|mandá|"
    r"escribí|probá|dejá|hacé|vení|revisá|tomá|sacá|poné|buscá|cerrá|abrí|sumá|"
    r"pasá|contá|mostrá|tocá|apretá|elegí|pedí|seguí|salí|agregá|volvé|dame)\b",
    re.IGNORECASE,
)


def _load():
    spec = importlib.util.spec_from_file_location("vigilantes", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_el_aviso_de_activacion_no_toca_la_base(monkeypatch) -> None:
    """--avisar-activacion manda el aviso y nunca corre la revision."""
    mod = _load()
    enviados: list[tuple[str, bool]] = []
    monkeypatch.setattr(mod, "_avisar", lambda texto, *, dry_run: enviados.append((texto, dry_run)))

    async def _no_debe_correr(_como_json):  # pragma: no cover - guardia, nunca se llama
        raise AssertionError("el aviso de activacion no corre la revision diaria")

    monkeypatch.setattr(mod, "_correr", _no_debe_correr)
    monkeypatch.setattr(mod.sys, "argv", ["vigilantes.py", "--avisar-activacion"])

    mod.main()

    assert [texto for texto, _ in enviados] == [mod.AVISO_ACTIVACION]
    assert enviados[0][1] is False


def test_el_aviso_de_activacion_en_modo_seco_no_manda_nada(monkeypatch) -> None:
    mod = _load()
    enviados: list[tuple[str, bool]] = []
    monkeypatch.setattr(mod, "_avisar", lambda texto, *, dry_run: enviados.append((texto, dry_run)))
    monkeypatch.setattr(mod.sys, "argv", ["vigilantes.py", "--avisar-activacion", "--dry-run"])

    mod.main()

    assert [dry_run for _, dry_run in enviados] == [True]


def test_la_copia_que_lee_la_duena_esta_en_espanol_neutro() -> None:
    mod = _load()
    encontrado = _VOSEO.search(mod.AVISO_ACTIVACION)
    assert encontrado is None, f"AVISO_ACTIVACION usa una forma regional: {encontrado.group(0)!r}"


def test_el_aviso_de_activacion_cuenta_los_chequeos_que_corren() -> None:
    """La copia no puede prometer un numero de chequeos distinto del que corre de verdad."""
    mod = _load()
    activos = {vigilante["id"] for vigilante in leer_vigilantes() if vigilante["activo"]}
    vinetas = [linea for linea in mod.AVISO_ACTIVACION.splitlines() if linea.startswith("•")]

    assert activos == {"V1", "V2", "V3", "V7"}
    assert len(vinetas) == len(activos), (
        f"el aviso promete {len(vinetas)} chequeo(s) y corren {len(activos)}"
    )

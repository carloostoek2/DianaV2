"""scripts/vigilantes.py — modo seco del vigilante.

El chequeo de verdad corre dentro del bot; este script existe para mirarlo a mano sin esperar
la corrida del dia y sin mandar nada. Lo que se prueba aca es que el modo seco no tenga efecto
y que el aviso de puesta en marcha salga una sola vez.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from diana.application.contract_watchdog_service import leer_vigilantes

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vigilantes.py"


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


def test_el_aviso_de_activacion_cuenta_los_chequeos_que_corren() -> None:
    """La copia no puede prometer un numero de chequeos distinto del que corre de verdad."""
    mod = _load()
    activos = {vigilante["id"] for vigilante in leer_vigilantes() if vigilante["activo"]}
    vinetas = [linea for linea in mod.AVISO_ACTIVACION.splitlines() if linea.startswith("•")]

    assert activos == {"V1", "V2", "V3", "V7"}
    assert len(vinetas) == len(activos), (
        f"el aviso promete {len(vinetas)} chequeo(s) y corren {len(activos)}"
    )

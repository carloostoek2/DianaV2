"""scripts/vigilantes.py — activation notice and the voice of the owner-facing copy.

The vigilance was announced with a hand-typed message that had drifted from the
copy the script itself sends (voseo in one, neutral Spanish in the other). The
notice now lives here, so it is reproducible and speaks like the alerts.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vigilantes.py"

# Voseo (present and imperative). The product copy uses neutral Spanish: "tú",
# never "vos". A hit here means the owner-facing text picked up a regional form.
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


def test_activation_notice_is_sent_once_and_skips_the_daily_check(monkeypatch) -> None:
    """--avisar-activacion sends the notice and never touches the database."""
    mod = _load()
    enviados: list[tuple[str, bool]] = []
    monkeypatch.setattr(mod, "avisar", lambda texto, *, dry_run: enviados.append((texto, dry_run)))

    async def _no_debe_correr(_vigilantes):  # pragma: no cover - guard, never called
        raise AssertionError("el aviso de activación no corre la revisión diaria")

    monkeypatch.setattr(mod, "revisar", _no_debe_correr)
    monkeypatch.setattr(mod.sys, "argv", ["vigilantes.py", "--avisar-activacion"])

    mod.main()

    assert [texto for texto, _ in enviados] == [mod.AVISO_ACTIVACION]
    assert enviados[0][1] is False


def test_activation_notice_dry_run_sends_nothing(monkeypatch) -> None:
    mod = _load()
    enviados: list[tuple[str, bool]] = []
    monkeypatch.setattr(mod, "avisar", lambda texto, *, dry_run: enviados.append((texto, dry_run)))
    monkeypatch.setattr(mod.sys, "argv", ["vigilantes.py", "--avisar-activacion", "--dry-run"])

    mod.main()

    assert [dry_run for _, dry_run in enviados] == [True]


def test_owner_facing_copy_stays_in_neutral_spanish() -> None:
    """Every text the owner can read: no voseo, no regional forms."""
    mod = _load()
    textos = {
        "AVISO_ACTIVACION": mod.AVISO_ACTIVACION,
        **{f"LINEA_DE_ALERTA[{k}]": v for k, v in mod.LINEA_DE_ALERTA.items()},
        **{f"SIGNIFICADO[{k}]": v for k, v in mod.SIGNIFICADO.items()},
    }
    for nombre, texto in textos.items():
        encontrado = _VOSEO.search(texto)
        assert encontrado is None, f"{nombre} usa una forma regional: {encontrado.group(0)!r}"


def test_activation_notice_names_the_three_active_watchers() -> None:
    """The notice promises three checks, matching what is actually deployed."""
    mod = _load()
    activos = {v["id"] for v in mod.leer_vigilantes() if v["activo"]}
    assert activos == {"V1", "V2", "V7"}
    assert mod.AVISO_ACTIVACION.count("• que ") == len(activos)

"""Aviso de arranque por banderas nucleo: registro, latido y aviso unico.

Lo que se exige: el resumen sale **siempre** en el registro, sale en ``/health``, y el mensaje a
la dueña sale **una sola vez** por advertencia. Y que nada de esto pueda frenar el arranque.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from diana.application import aviso_banderas
from diana.application.aviso_banderas import (
    avisar_banderas_nucleo,
    escribir_estado,
    leer_bloque_banderas,
    leer_estado,
    leer_variables_feature,
    valores_de_settings,
)
from diana.config import banderas_nucleo
from diana.config.banderas_nucleo import BanderaNucleo
from diana.config.settings import Settings


def _campos_feature() -> set[str]:
    return {nombre for nombre in Settings.model_fields if nombre.startswith("feature_")}


def _settings(**apagadas: bool) -> Settings:
    """Todas las banderas encendidas, salvo las que se nombren apagadas."""
    valores: dict[str, Any] = {campo: True for campo in _campos_feature()}
    valores.update(apagadas)
    return Settings.model_construct(**valores)


class _Notifier:
    def __init__(self, *, falla: bool = False) -> None:
        self.mensajes: list[str] = []
        self._falla = falla

    async def notify_info(self, text: str, *, chat_id: int | None = None) -> None:
        if self._falla:
            raise RuntimeError("telegram caido")
        self.mensajes.append(text)


class _App:
    def __init__(self, settings: Settings, notifier: _Notifier) -> None:
        self.settings = settings
        self.notifier = notifier


@pytest.fixture
def entorno(tmp_path: Path) -> Path:
    """Un `.env` de prueba, con una bandera mal escrita que el codigo no reconoce."""
    ruta = tmp_path / ".env"
    ruta.write_text(
        "# comentario que no cuenta\n"
        "TELEGRAM_BOT_TOKEN=123:abc\n"
        "FEATURE_MEMORY_ENABLED=true\n"
        "export FEATURE_RECONTACT_ENABLED=false\n"
        "# FEATURE_PROMO_ENABLED=false\n"
        "FEATURE_MEMORIA_ENABLED=true\n",
        encoding="utf-8",
    )
    return ruta


@pytest.fixture
def entorno_sin_banderas(tmp_path: Path) -> Path:
    """Un `.env` sin ninguna bandera: aisla del archivo real de la maquina."""
    ruta = tmp_path / ".env.limpio"
    ruta.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    return ruta


# ---------------------------------------------------------------------------
# Lectura del entorno
# ---------------------------------------------------------------------------
def test_lee_las_variables_feature_del_archivo(entorno: Path) -> None:
    nombres = leer_variables_feature(entorno)

    assert "FEATURE_MEMORY_ENABLED" in nombres
    assert "FEATURE_RECONTACT_ENABLED" in nombres, "el prefijo export tiene que contar"
    assert "FEATURE_MEMORIA_ENABLED" in nombres
    assert "TELEGRAM_BOT_TOKEN" not in nombres


def test_las_lineas_comentadas_no_cuentan(entorno: Path) -> None:
    assert "FEATURE_PROMO_ENABLED" not in leer_variables_feature(entorno)


def test_archivo_de_entorno_ausente_no_es_error(tmp_path: Path) -> None:
    assert leer_variables_feature(tmp_path / "no-existe.env") == frozenset()


def test_valores_de_settings_toma_todas_las_banderas() -> None:
    valores = valores_de_settings(_settings(feature_memory_enabled=False))

    assert set(valores) == _campos_feature()
    assert valores["feature_memory_enabled"] is False
    assert valores["feature_promo_enabled"] is True


# ---------------------------------------------------------------------------
# Latido
# ---------------------------------------------------------------------------
def test_estado_ida_y_vuelta_sin_temporales(tmp_path: Path) -> None:
    ruta = tmp_path / "banderas.json"

    escribir_estado({"format_version": 1, "huella": "abc", "health": {"ok": True}}, ruta)

    assert leer_estado(ruta) == {"format_version": 1, "huella": "abc", "health": {"ok": True}}
    assert leer_bloque_banderas(ruta) == {"ok": True}
    assert list(tmp_path.glob(".banderas-*")) == [], "la escritura tiene que ser atomica"


def test_estado_corrupto_no_levanta(tmp_path: Path) -> None:
    ruta = tmp_path / "banderas.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")

    assert leer_estado(ruta) is None
    assert leer_bloque_banderas(ruta) is None


def test_sin_estado_previo_no_hay_bloque(tmp_path: Path) -> None:
    assert leer_bloque_banderas(tmp_path / "no-existe.json") is None


# ---------------------------------------------------------------------------
# El aviso
# ---------------------------------------------------------------------------
async def test_avisa_cuando_hay_bandera_sin_declarar(
    tmp_path: Path, entorno: Path, caplog: pytest.LogCaptureFixture
) -> None:
    notifier = _Notifier()
    app = _App(_settings(feature_memory_enabled=False), notifier)
    ruta = tmp_path / "banderas.json"

    with caplog.at_level(logging.INFO, logger="diana.application"):
        estado = await avisar_banderas_nucleo(app, env_path=entorno, state_path=ruta)

    assert estado is not None
    assert "FEATURE_MEMORY_ENABLED" in estado.para_health()["sin_declarar"]
    assert notifier.mensajes, "una bandera nucleo apagada sin declarar tiene que avisar"
    assert "FEATURE_MEMORY_ENABLED" in notifier.mensajes[0]
    assert [r.levelname for r in caplog.records] == ["WARNING"]
    assert caplog.records[0].event == "banderas_nucleo"  # type: ignore[attr-defined]


async def test_el_bloque_del_registro_nombra_motivo_y_fecha(
    tmp_path: Path, entorno_sin_banderas: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = _App(_settings(feature_history_reimport_enabled=False), _Notifier())
    ruta = tmp_path / "banderas.json"

    with caplog.at_level(logging.INFO, logger="diana.application"):
        await avisar_banderas_nucleo(app, env_path=entorno_sin_banderas, state_path=ruta)

    mensaje = caplog.records[0].getMessage()
    assert "FEATURE_HISTORY_REIMPORT_ENABLED" in mensaje
    assert "2026-09-06" in mensaje
    assert "Apagadas a proposito" in mensaje


async def test_no_repite_el_aviso_si_nada_cambio(tmp_path: Path, entorno: Path) -> None:
    ruta = tmp_path / "banderas.json"
    notifier = _Notifier()
    app = _App(_settings(feature_memory_enabled=False), notifier)

    await avisar_banderas_nucleo(app, env_path=entorno, state_path=ruta)
    await avisar_banderas_nucleo(app, env_path=entorno, state_path=ruta)

    assert len(notifier.mensajes) == 1, "un aviso que llega en cada reinicio se vuelve ruido"


async def test_vuelve_a_avisar_si_cambio_la_lista(tmp_path: Path, entorno: Path) -> None:
    ruta = tmp_path / "banderas.json"
    notifier = _Notifier()

    await avisar_banderas_nucleo(
        _App(_settings(feature_memory_enabled=False), notifier), env_path=entorno, state_path=ruta
    )
    await avisar_banderas_nucleo(
        _App(_settings(feature_memory_enabled=False, feature_promo_enabled=False), notifier),
        env_path=entorno,
        state_path=ruta,
    )

    assert len(notifier.mensajes) == 2
    assert "FEATURE_PROMO_ENABLED" in notifier.mensajes[1]


async def test_no_avisa_si_todo_lo_apagado_esta_declarado(
    tmp_path: Path, entorno_sin_banderas: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """El caso de la recarga de historial: apagada a proposito no genera mensaje."""
    ruta = tmp_path / "banderas.json"
    notifier = _Notifier()
    app = _App(_settings(feature_history_reimport_enabled=False), notifier)

    with caplog.at_level(logging.INFO, logger="diana.application"):
        estado = await avisar_banderas_nucleo(
            app, env_path=entorno_sin_banderas, state_path=ruta
        )

    assert estado is not None and estado.hay_advertencia is False
    assert notifier.mensajes == []
    assert [r.levelname for r in caplog.records] == ["INFO"]


async def test_sin_nada_apagado_el_registro_es_una_sola_linea(
    tmp_path: Path,
    entorno_sin_banderas: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El registro sale siempre (es el comprobante de que el chequeo corrio), pero corto."""
    monkeypatch.setattr(
        banderas_nucleo,
        "CATALOGO",
        (BanderaNucleo(campo="feature_memory_enabled", que_se_pierde="x"),),
    )
    ruta = tmp_path / "banderas.json"
    app = _App(_settings(), _Notifier())

    with caplog.at_level(logging.INFO, logger="diana.application"):
        estado = await avisar_banderas_nucleo(app, env_path=entorno_sin_banderas, state_path=ruta)

    assert estado is not None and estado.hay_algo_que_contar is False
    assert [r.levelname for r in caplog.records] == ["INFO"]
    assert "\n" not in caplog.records[0].getMessage()


async def test_estado_previo_ilegible_avisa_igual(tmp_path: Path, entorno: Path) -> None:
    """Fail-open: mejor avisar de mas que perder el aviso por un archivo roto."""
    ruta = tmp_path / "banderas.json"
    ruta.write_text("no es json", encoding="utf-8")
    notifier = _Notifier()

    await avisar_banderas_nucleo(
        _App(_settings(feature_memory_enabled=False), notifier), env_path=entorno, state_path=ruta
    )

    assert len(notifier.mensajes) == 1


async def test_un_fallo_del_notificador_no_rompe_el_arranque(
    tmp_path: Path, entorno: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ruta = tmp_path / "banderas.json"
    app = _App(_settings(feature_memory_enabled=False), _Notifier(falla=True))

    with caplog.at_level(logging.INFO, logger="diana.application"):
        estado = await avisar_banderas_nucleo(app, env_path=entorno, state_path=ruta)

    assert estado is not None, "el arranque sigue aunque Telegram falle"
    assert "banderas_arranque_aviso_no_enviado" in [r.getMessage() for r in caplog.records]


async def test_si_los_ajustes_no_se_pueden_leer_no_frena(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class _Roto:
        @property
        def settings(self) -> Any:
            raise RuntimeError("settings ilegibles")

    with caplog.at_level(logging.INFO, logger="diana.application"):
        estado = await avisar_banderas_nucleo(_Roto(), state_path=tmp_path / "b.json")

    assert estado is None
    assert "banderas_arranque_fallo" in [r.getMessage() for r in caplog.records]


async def test_publica_el_resumen_para_health(tmp_path: Path, entorno: Path) -> None:
    ruta = tmp_path / "banderas.json"
    app = _App(_settings(feature_memory_enabled=False), _Notifier())

    await avisar_banderas_nucleo(app, env_path=entorno, state_path=ruta)

    bloque = leer_bloque_banderas(ruta)
    assert bloque is not None
    assert bloque["ok"] is False
    assert "FEATURE_MEMORY_ENABLED" in bloque["sin_declarar"]
    assert bloque["nombres_desconocidos"] == ["FEATURE_MEMORIA_ENABLED"]


async def test_el_latido_guardado_trae_version_y_huella(tmp_path: Path, entorno: Path) -> None:
    ruta = tmp_path / "banderas.json"
    app = _App(_settings(feature_memory_enabled=False), _Notifier())

    estado = await avisar_banderas_nucleo(app, env_path=entorno, state_path=ruta)

    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert guardado["format_version"] == aviso_banderas.STATE_FORMAT_VERSION
    assert estado is not None and guardado["huella"] == estado.huella_advertencia()

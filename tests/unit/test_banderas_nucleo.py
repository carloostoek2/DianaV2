"""Catalogo de banderas nucleo: comparacion pura y anti-putrefaccion.

Estas pruebas no arrancan el bot ni tocan la base: el catalogo es dato y la comparacion es una
funcion pura. Lo que se exige es que el catalogo **no se pudra**: toda bandera de ``Settings``
tiene que estar clasificada, y toda declaracion de apagado tiene que traer motivo, fecha y
condicion de reactivacion.
"""

from __future__ import annotations

from datetime import date

import pytest

from diana.config import banderas_nucleo
from diana.config.banderas_nucleo import (
    CATALOGO,
    FUERA_DEL_CATALOGO,
    ApagadoDeclarado,
    BanderaNucleo,
    estado_banderas,
    variables_desconocidas,
)
from diana.config.settings import Settings


def _campos_feature() -> set[str]:
    return {nombre for nombre in Settings.model_fields if nombre.startswith("feature_")}


def _valores(**encendidas: bool) -> dict[str, bool]:
    """Todos los campos feature_* en False, salvo los que se nombren."""
    base = {campo: False for campo in _campos_feature()}
    base.update(encendidas)
    return base


# ---------------------------------------------------------------------------
# Anti-putrefaccion del catalogo
# ---------------------------------------------------------------------------
def test_catalogo_cubre_todas_las_banderas_de_settings() -> None:
    """Una bandera nueva sin clasificar es un defecto, no una decision."""
    cubiertas = {b.campo for b in CATALOGO} | set(FUERA_DEL_CATALOGO)
    sin_clasificar = _campos_feature() - cubiertas
    assert not sin_clasificar, (
        "Estas banderas existen en Settings y no estan ni en CATALOGO ni en FUERA_DEL_CATALOGO: "
        f"{sorted(sin_clasificar)}"
    )


def test_catalogo_y_exclusiones_no_se_solapan() -> None:
    repetidas = {b.campo for b in CATALOGO} & set(FUERA_DEL_CATALOGO)
    assert not repetidas, f"Una bandera no puede ser nucleo y estar excluida a la vez: {repetidas}"


def test_catalogo_no_nombra_banderas_inexistentes() -> None:
    fantasma = {b.campo for b in CATALOGO} - _campos_feature()
    assert not fantasma, f"El catalogo nombra banderas que Settings no tiene: {sorted(fantasma)}"


def test_toda_bandera_nucleo_explica_que_se_pierde() -> None:
    vacias = [b.campo for b in CATALOGO if not b.que_se_pierde.strip()]
    assert not vacias, f"Sin frase de negocio, el aviso no dice nada util: {vacias}"


def test_toda_exclusion_tiene_motivo() -> None:
    vacias = [campo for campo, motivo in FUERA_DEL_CATALOGO.items() if not motivo.strip()]
    assert not vacias, f"Excluir una bandera sin motivo es lo mismo que olvidarla: {vacias}"


def test_toda_declaracion_tiene_fecha_motivo_y_condicion() -> None:
    for bandera in CATALOGO:
        declaracion = bandera.apagada_a_proposito
        if declaracion is None:
            continue
        assert isinstance(declaracion.desde, date), f"{bandera.campo}: falta la fecha"
        assert declaracion.motivo.strip(), f"{bandera.campo}: falta el motivo"
        assert declaracion.condicion_para_reactivar.strip(), (
            f"{bandera.campo}: falta la condicion para reactivarla"
        )


def test_la_variable_del_entorno_se_deriva_del_campo() -> None:
    assert BanderaNucleo(campo="feature_memory_enabled", que_se_pierde="x").variable == (
        "FEATURE_MEMORY_ENABLED"
    )


# ---------------------------------------------------------------------------
# Comparacion: con y sin declaracion
# ---------------------------------------------------------------------------
@pytest.fixture
def catalogo_de_prueba(monkeypatch: pytest.MonkeyPatch):
    """Catalogo minimo: una bandera sin declarar y la misma con declaracion."""

    def _instalar(*, declarada: bool) -> None:
        declaracion = (
            ApagadoDeclarado(
                desde=date(2026, 9, 6),
                motivo="La sesion configurada es la de la cuenta anterior.",
                condicion_para_reactivar="Reautorizar la sesion con la cuenta en uso.",
            )
            if declarada
            else None
        )
        monkeypatch.setattr(
            banderas_nucleo,
            "CATALOGO",
            (
                BanderaNucleo(
                    campo="feature_memory_enabled",
                    que_se_pierde="Diana deja de recordar lo que el VIP conto antes.",
                    apagada_a_proposito=declaracion,
                ),
            ),
        )
        monkeypatch.setattr(banderas_nucleo, "FUERA_DEL_CATALOGO", {})

    return _instalar


def test_bandera_nucleo_apagada_sin_declarar_va_a_la_advertencia(catalogo_de_prueba) -> None:
    catalogo_de_prueba(declarada=False)

    estado = estado_banderas(_valores(feature_memory_enabled=False))

    assert [b.variable for b in estado.apagadas_sin_declarar] == ["FEATURE_MEMORY_ENABLED"]
    assert estado.apagadas_declaradas == ()
    assert estado.hay_advertencia is True
    assert "FEATURE_MEMORY_ENABLED" in estado.mensaje_aviso()


def test_bandera_nucleo_apagada_declarada_no_genera_advertencia(catalogo_de_prueba) -> None:
    """Declarar el apagado con motivo y fecha es justamente lo que silencia el aviso."""
    catalogo_de_prueba(declarada=True)

    estado = estado_banderas(_valores(feature_memory_enabled=False))

    assert [b.variable for b in estado.apagadas_declaradas] == ["FEATURE_MEMORY_ENABLED"]
    assert estado.apagadas_sin_declarar == ()
    assert estado.hay_advertencia is False
    assert estado.mensaje_aviso() is None


def test_el_aviso_declarado_muestra_motivo_y_fecha(catalogo_de_prueba) -> None:
    catalogo_de_prueba(declarada=True)

    bloque = "\n".join(estado_banderas(_valores()).bloque_legible())

    assert "2026-09-06" in bloque
    assert "cuenta anterior" in bloque
    assert "Reautorizar" in bloque


def test_bandera_nucleo_encendida_no_aparece() -> None:
    estado = estado_banderas(_valores(feature_memory_enabled=True))

    assert "FEATURE_MEMORY_ENABLED" in estado.encendidas
    apagadas = {b.variable for b in estado.apagadas_sin_declarar} | {
        b.variable for b in estado.apagadas_declaradas
    }
    assert "FEATURE_MEMORY_ENABLED" not in apagadas


def test_declaracion_obsoleta_cuando_la_bandera_esta_encendida() -> None:
    """Una nota de apagado que quedo vieja se reporta: es la clase de error del .env.example."""
    estado = estado_banderas(_valores(feature_history_reimport_enabled=True))

    assert "FEATURE_HISTORY_REIMPORT_ENABLED" in estado.declaraciones_obsoletas
    assert "FEATURE_HISTORY_REIMPORT_ENABLED" in estado.encendidas


def test_caso_real_recarga_de_historial() -> None:
    """El primer caso declarado del proyecto: apagada a proposito desde el 2026-09-06."""
    estado = estado_banderas(_valores())

    declaradas = {b.variable: b for b in estado.apagadas_declaradas}
    assert "FEATURE_HISTORY_REIMPORT_ENABLED" in declaradas
    declaracion = declaradas["FEATURE_HISTORY_REIMPORT_ENABLED"].declaracion
    assert declaracion is not None
    assert declaracion.desde == date(2026, 9, 6)
    assert "FEATURE_HISTORY_REIMPORT_ENABLED" not in {
        b.variable for b in estado.apagadas_sin_declarar
    }


# ---------------------------------------------------------------------------
# Banderas que el codigo no reconoce
# ---------------------------------------------------------------------------
def test_variable_del_entorno_que_el_codigo_no_conoce() -> None:
    """Hoy Settings la descarta en silencio; el resumen tiene que hacerla visible."""
    estado = estado_banderas(_valores(feature_memory_enabled=True), ["FEATURE_MEMORIA_ENABLED"])

    assert estado.desconocidas == ("FEATURE_MEMORIA_ENABLED",)
    assert estado.hay_advertencia is True


def test_variable_del_entorno_ajena_a_las_banderas_se_ignora(catalogo_de_prueba) -> None:
    """El ``.env`` tiene secretos y ajustes que no son banderas: ninguno entra al resumen."""
    catalogo_de_prueba(declarada=True)

    estado = estado_banderas(
        _valores(feature_memory_enabled=True), ["TELEGRAM_BOT_TOKEN", "DATABASE_URL"]
    )

    assert estado.desconocidas == ()
    assert estado.hay_advertencia is False


def test_variables_desconocidas_ordena_y_no_repite() -> None:
    assert variables_desconocidas(
        ["FEATURE_ZETA", "FEATURE_ALFA", "FEATURE_ZETA", "OTRA"],
        conocidas=["FEATURE_ALFA"],
    ) == ["FEATURE_ZETA"]


# ---------------------------------------------------------------------------
# Huella para no repetir el aviso
# ---------------------------------------------------------------------------
def test_huella_estable_y_sensible_al_cambio(catalogo_de_prueba) -> None:
    catalogo_de_prueba(declarada=False)

    primera = estado_banderas(_valores(feature_memory_enabled=False)).huella_advertencia()
    repetida = estado_banderas(_valores(feature_memory_enabled=False)).huella_advertencia()
    cambiada = estado_banderas(
        _valores(feature_memory_enabled=False), ["FEATURE_MEMORIA_ENABLED"]
    ).huella_advertencia()

    assert primera == repetida, "Dos arranques iguales tienen que dar la misma huella"
    assert primera != cambiada, "Si cambia la advertencia, el aviso tiene que volver a salir"


def test_huella_no_depende_del_orden_de_las_variables() -> None:
    un_orden = estado_banderas(_valores(), ["FEATURE_B", "FEATURE_A"]).huella_advertencia()
    otro_orden = estado_banderas(_valores(), ["FEATURE_A", "FEATURE_B"]).huella_advertencia()

    assert un_orden == otro_orden


def test_la_huella_solo_mira_lo_que_no_esta_declarado() -> None:
    """Encender una bandera declarada no cambia la advertencia, asi que no debe reavisar."""
    apagada = _valores()
    encendida = _valores(feature_history_reimport_enabled=True)

    assert estado_banderas(apagada).huella_advertencia() == (
        estado_banderas(encendida).huella_advertencia()
    )


# ---------------------------------------------------------------------------
# Bloque publicable
# ---------------------------------------------------------------------------
def test_bloque_de_health_cuenta_y_nombra() -> None:
    estado = estado_banderas(_valores(feature_memory_enabled=True))
    bloque = estado.para_health()

    assert bloque["ok"] is False
    assert bloque["nucleo_total"] == len(CATALOGO)
    assert bloque["apagadas_sin_declarar"] == len(estado.apagadas_sin_declarar)
    assert isinstance(bloque["sin_declarar"], list)
    assert "FEATURE_RECONTACT_ENABLED" in bloque["sin_declarar"]


def test_bloque_de_health_no_lleva_secretos() -> None:
    blob = str(estado_banderas(_valores()).para_health()).lower()

    for prohibido in ("token", "password", "secret", "api_key", "database_url"):
        assert prohibido not in blob

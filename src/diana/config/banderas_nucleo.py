"""Catalogo de banderas nucleo y declaracion de los apagados a proposito.

Una bandera apagada hoy solo se ve en el registro tecnico, en ingles, en medio de cientos de
lineas: ``FEATURE_HISTORY_REIMPORT_ENABLED=false`` convivio un mes con un comentario que decia lo
contrario, y nadie lo noto hasta una auditoria (``audit/INVESTIGACION-C.md``).

Este modulo responde una sola pregunta: **de las banderas nucleo, cuales estan apagadas, cuales se
apagaron a proposito con motivo y fecha, y cuales no estan declaradas**.

Es dato puro: no lee archivos, no toca la base y no habla con Telegram. La comparacion
(:func:`estado_banderas`) se prueba sin dobles.

Criterio de nucleo: si la bandera esta apagada, algo que el negocio recibe o que la dueña controla
deja de ocurrir. Quedan fuera las que **solo miden** y los interruptores que se apagan a proposito
por seguridad; cada exclusion lleva su motivo en :data:`FUERA_DEL_CATALOGO`.

Regla de mantenimiento: todo campo ``feature_*`` de ``Settings`` tiene que estar en
:data:`CATALOGO` o en :data:`FUERA_DEL_CATALOGO`. Una prueba lo exige, para que el catalogo no se
pudra cuando alguien agregue una bandera nueva.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

__all__ = [
    "CATALOGO",
    "FUERA_DEL_CATALOGO",
    "ApagadoDeclarado",
    "BanderaApagada",
    "BanderaNucleo",
    "EstadoBanderas",
    "estado_banderas",
    "variables_desconocidas",
]


@dataclass(frozen=True)
class ApagadoDeclarado:
    """Por que una bandera nucleo esta apagada, desde cuando y cuando se reactiva."""

    desde: date
    motivo: str
    condicion_para_reactivar: str


@dataclass(frozen=True)
class BanderaNucleo:
    """Una bandera que, apagada, cambia lo que el negocio recibe o lo que la dueña controla."""

    campo: str
    """Nombre del campo en ``Settings`` (``feature_memory_enabled``)."""

    que_se_pierde: str
    """Que deja de ocurrir, en lenguaje de negocio."""

    apagada_a_proposito: ApagadoDeclarado | None = None
    """Declaracion del apagado. ``None`` = si esta apagada, hay que avisar."""

    @property
    def variable(self) -> str:
        """Nombre de la variable en el ``.env`` (``FEATURE_MEMORY_ENABLED``)."""
        return self.campo.upper()


#: Banderas nucleo. El orden es el de lectura del resumen, no alfabetico.
CATALOGO: tuple[BanderaNucleo, ...] = (
    BanderaNucleo(
        campo="feature_memory_enabled",
        que_se_pierde="Diana deja de recordar lo que el VIP conto antes.",
    ),
    BanderaNucleo(
        campo="feature_context_enabled",
        que_se_pierde="Se pierde el hilo de lo hablado en los ultimos dias.",
    ),
    BanderaNucleo(
        campo="feature_gray_zone_enabled",
        que_se_pierde="Cuando falta una regla, el caso no se consulta ni se congela.",
    ),
    BanderaNucleo(
        campo="feature_gray_zone_proposal_enabled",
        que_se_pierde="La consulta de doctrina llega sin propuesta de regla.",
    ),
    BanderaNucleo(
        campo="feature_staging_enabled",
        que_se_pierde="Las correcciones de la dueña no se guardan como aprendizaje.",
    ),
    BanderaNucleo(
        campo="feature_quality_feedback_enabled",
        que_se_pierde="Desaparecen Destacar y Reprender de la cola de aprobacion.",
    ),
    BanderaNucleo(
        campo="feature_general_mode_enabled",
        que_se_pierde="El canal de Atencion (no-VIP) deja de operar.",
    ),
    BanderaNucleo(
        campo="feature_promo_enabled",
        que_se_pierde="Los mensajes de promocion dejan de responderse.",
    ),
    BanderaNucleo(
        campo="feature_image_vision_enabled",
        que_se_pierde="Diana deja de describir las imagenes: solo ve la etiqueta.",
    ),
    BanderaNucleo(
        campo="feature_video_vision_enabled",
        que_se_pierde="Diana deja de describir los videos.",
    ),
    BanderaNucleo(
        campo="feature_pii_masking_enabled",
        que_se_pierde="Sale del camino la proteccion de datos personales.",
    ),
    BanderaNucleo(
        campo="feature_vip_history_seed_enabled",
        que_se_pierde="Un VIP nuevo arranca sin su historial previo.",
    ),
    BanderaNucleo(
        campo="feature_history_reimport_enabled",
        que_se_pierde="Los VIP ya registrados no completan su historial.",
        apagada_a_proposito=ApagadoDeclarado(
            desde=date(2026, 9, 6),
            motivo=(
                "La sesion de Telegram configurada es la de la cuenta anterior: la cuenta en uso "
                "no tiene historial con los VIP ya registrados, asi que la recarga no encontraria "
                "mensajes que importar."
            ),
            condicion_para_reactivar=(
                "Una sesion de Telegram de una cuenta que si tenga los chats con los VIP. Ojo: el "
                "alta de un VIP nuevo si importa historial con la misma sesion y NO depende de "
                "esta bandera."
            ),
        ),
    ),
    BanderaNucleo(
        campo="feature_recontact_enabled",
        que_se_pierde="Los VIP que se quedan callados no reciben recontacto.",
    ),
    BanderaNucleo(
        campo="feature_contract_watchdog_enabled",
        que_se_pierde="Nadie revisa a diario que lo prometido siga ocurriendo.",
    ),
    BanderaNucleo(
        campo="feature_escalation_fp_draft_enabled",
        que_se_pierde="Marcar un falso positivo ya no reanuda el caso.",
    ),
    BanderaNucleo(
        campo="feature_persona_operacion_enabled",
        que_se_pierde="Diana deja de usar los datos internos del negocio.",
    ),
    BanderaNucleo(
        campo="feature_link_enabled",
        que_se_pierde="El aviso de expulsiones de Lucien deja de llegar.",
    ),
    BanderaNucleo(
        campo="feature_advanced_behavior",
        que_se_pierde="Los mensajes largos vuelven a salir de un solo bloque.",
    ),
    BanderaNucleo(
        campo="feature_phatic_auto_send",
        que_se_pierde="Los saludos vuelven a la cola de aprobacion.",
    ),
)


#: Campos ``feature_*`` de ``Settings`` que NO son nucleo, cada uno con su motivo.
FUERA_DEL_CATALOGO: Mapping[str, str] = {
    "feature_autonomous_mode": (
        "Interruptor de seguridad (kill-switch L1 del envio autonomo). Apagado es su estado "
        "correcto hasta que la dueña lo encienda."
    ),
    "feature_calibration_enabled": (
        "Job que ajusta umbrales; es un interruptor de seguridad que espera a operaciones."
    ),
    "feature_sandbox_enabled": (
        "Superficie de prueba de la dueña: no cambia lo que recibe el negocio."
    ),
    "feature_sandbox_auto_send": (
        "Superficie de prueba de la dueña: no cambia lo que recibe el negocio."
    ),
    "feature_persona_admin_enabled": "Superficie interna de administracion de la persona.",
    "feature_force_profile_when_notes": (
        "Regla interna del pipeline; su efecto se ve en el borrador, no en una capacidad del "
        "negocio que se pierda."
    ),
    "feature_persona_semantic_shadow": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_emotional_detector_enabled": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_profile_synthesis_enabled": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_phatic_autonomy": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_mood_engine": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_trust_budget": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_severity_trust_decrement_enabled": (
        "Solo mide (shadow): no cambia lo que recibe el VIP."
    ),
    "feature_autonomy_readiness_enabled": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_autonomy_coincidence_enabled": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_autonomy_quality_enabled": "Solo mide (shadow): no cambia lo que recibe el VIP.",
    "feature_autonomy_recommendation_enabled": (
        "Solo mide y recomienda; nunca envia por su cuenta."
    ),
}


@dataclass(frozen=True)
class BanderaApagada:
    """Una bandera nucleo apagada, con su declaracion si la tiene."""

    variable: str
    que_se_pierde: str
    declaracion: ApagadoDeclarado | None = None

    @property
    def declarada(self) -> bool:
        return self.declaracion is not None


@dataclass(frozen=True)
class EstadoBanderas:
    """Foto de las banderas nucleo en un momento dado."""

    encendidas: tuple[str, ...]
    apagadas_declaradas: tuple[BanderaApagada, ...]
    apagadas_sin_declarar: tuple[BanderaApagada, ...]
    desconocidas: tuple[str, ...]
    declaraciones_obsoletas: tuple[str, ...]

    @property
    def nucleo_total(self) -> int:
        return len(self.encendidas) + len(self.apagadas_declaradas) + len(self.apagadas_sin_declarar)

    @property
    def hay_advertencia(self) -> bool:
        """Hay algo que revisar: una apagada sin declarar o una bandera que el codigo no conoce."""
        return bool(self.apagadas_sin_declarar or self.desconocidas)

    @property
    def hay_algo_que_contar(self) -> bool:
        """Hay algo para mostrar en el resumen, aunque no sea una advertencia."""
        return bool(
            self.apagadas_declaradas
            or self.apagadas_sin_declarar
            or self.desconocidas
            or self.declaraciones_obsoletas
        )

    def huella_advertencia(self) -> str:
        """Identifica **lo que hay que advertir**, sin la hora.

        Dos arranques con la misma advertencia dan la misma huella: es lo que permite no repetir
        el mensaje a la dueña. No entra lo declarado, porque declarar algo no genera aviso.
        """
        crudo = json.dumps(
            {
                "sin_declarar": sorted(b.variable for b in self.apagadas_sin_declarar),
                "desconocidas": sorted(self.desconocidas),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]

    def para_health(self) -> dict[str, Any]:
        """Bloque publicable en ``/health``. Sin secretos: solo nombres de bandera y conteos."""
        return {
            "ok": not self.hay_advertencia,
            "nucleo_total": self.nucleo_total,
            "apagadas_declaradas": len(self.apagadas_declaradas),
            "apagadas_sin_declarar": len(self.apagadas_sin_declarar),
            "desconocidas": len(self.desconocidas),
            "sin_declarar": [b.variable for b in self.apagadas_sin_declarar],
            "nombres_desconocidos": list(self.desconocidas),
            "declaraciones_obsoletas": list(self.declaraciones_obsoletas),
        }

    def para_registro(self) -> dict[str, Any]:
        """Campos estructurados del registro, para poder buscar el aviso en el historial."""
        return {
            "event": "banderas_nucleo",
            "advertencia": self.hay_advertencia,
            "apagadas_declaradas": [b.variable for b in self.apagadas_declaradas],
            "apagadas_sin_declarar": [b.variable for b in self.apagadas_sin_declarar],
            "desconocidas": list(self.desconocidas),
            "declaraciones_obsoletas": list(self.declaraciones_obsoletas),
            "nucleo_total": self.nucleo_total,
            "huella": self.huella_advertencia(),
        }

    def resumen_corto(self) -> str:
        """Una linea, para el registro cuando no hay nada que advertir."""
        return (
            f"Banderas nucleo: {self.nucleo_total} en total, "
            f"{len(self.apagadas_declaradas)} apagada(s) a proposito, "
            f"{len(self.apagadas_sin_declarar)} apagada(s) sin declarar, "
            f"{len(self.desconocidas)} desconocida(s)."
        )

    def bloque_legible(self) -> list[str]:
        """El resumen como texto, para leer de corrido y sin nombres de tabla."""
        lineas: list[str] = []
        if self.apagadas_declaradas:
            lineas.append("Apagadas a proposito (declaradas):")
            for bandera in self.apagadas_declaradas:
                declaracion = bandera.declaracion
                lineas.append(f"  - {bandera.que_se_pierde}")
                if declaracion is not None:
                    lineas.append(
                        f"    {bandera.variable}: {declaracion.motivo} "
                        f"(apagada desde el {declaracion.desde.isoformat()})"
                    )
                    lineas.append(f"    Se reactiva cuando: {declaracion.condicion_para_reactivar}")
        if self.apagadas_sin_declarar:
            lineas.append("Apagadas SIN declarar (revisar):")
            for bandera in self.apagadas_sin_declarar:
                lineas.append(f"  - {bandera.que_se_pierde} ({bandera.variable})")
        if self.desconocidas:
            lineas.append("Escritas en el entorno y no reconocidas por el codigo (revisar):")
            for nombre in self.desconocidas:
                lineas.append(
                    f"  - {nombre}: el sistema la ignora, asi que opera como si estuviera apagada."
                )
        if self.declaraciones_obsoletas:
            lineas.append("Declaradas como apagadas y hoy encendidas (la nota quedo vieja):")
            for nombre in self.declaraciones_obsoletas:
                lineas.append(f"  - {nombre}")
        return lineas

    def mensaje_aviso(self) -> str | None:
        """Aviso corto por Telegram. ``None`` si no hay nada que advertir."""
        if not self.hay_advertencia:
            return None
        lineas = ["Banderas nucleo que conviene revisar:"]
        lineas.extend(self.bloque_legible())
        return "\n".join(lineas)


def estado_banderas(
    valores: Mapping[str, bool],
    variables_en_env: Iterable[str] = (),
) -> EstadoBanderas:
    """Compara las banderas nucleo contra sus valores reales. Funcion pura.

    ``valores`` mapea el nombre del campo de ``Settings`` a su valor efectivo.
    ``variables_en_env`` son los nombres de variable activos en el entorno (``FEATURE_*``); las
    que el codigo no conoce se reportan aparte, porque hoy se descartan en silencio.
    """
    encendidas: list[str] = []
    declaradas: list[BanderaApagada] = []
    sin_declarar: list[BanderaApagada] = []
    obsoletas: list[str] = []

    for bandera in CATALOGO:
        if valores.get(bandera.campo, False):
            encendidas.append(bandera.variable)
            if bandera.apagada_a_proposito is not None:
                obsoletas.append(bandera.variable)
            continue
        apagada = BanderaApagada(
            variable=bandera.variable,
            que_se_pierde=bandera.que_se_pierde,
            declaracion=bandera.apagada_a_proposito,
        )
        if apagada.declarada:
            declaradas.append(apagada)
        else:
            sin_declarar.append(apagada)

    conocidas = {bandera.variable for bandera in CATALOGO} | {
        campo.upper() for campo in FUERA_DEL_CATALOGO
    }
    return EstadoBanderas(
        encendidas=tuple(encendidas),
        apagadas_declaradas=tuple(declaradas),
        apagadas_sin_declarar=tuple(sin_declarar),
        desconocidas=tuple(variables_desconocidas(variables_en_env, conocidas)),
        declaraciones_obsoletas=tuple(obsoletas),
    )


def variables_desconocidas(
    variables_en_env: Iterable[str],
    conocidas: Iterable[str],
) -> list[str]:
    """Banderas ``FEATURE_*`` del entorno que el codigo no reconoce, en orden alfabetico.

    ``Settings`` carga con ``extra="ignore"``: una bandera mal escrita o ya retirada se descarta
    sin decir nada y el sistema opera como si estuviera apagada. Aqui se hace visible.
    """
    reconocidas = set(conocidas)
    return sorted(
        {
            nombre
            for nombre in variables_en_env
            if nombre.startswith("FEATURE_") and nombre not in reconocidas
        }
    )

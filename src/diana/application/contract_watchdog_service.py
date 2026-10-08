"""ContractWatchdogService — chequeo diario, solo lectura, de que los efectos prometidos siguen ocurriendo.

Por que existe: una prueba en verde dice que el efecto ocurria **el dia que se midio**. Si
manana una pieza se desconecta (una bandera que se apaga, un guardado que vuelve a pisar una
columna, el motor de huellas que devuelve ceros), nada avisa: el producto sigue funcionando y
el registro deja de existir en silencio. Este servicio es el que avisa.

Tres reglas que lo definen:

* **Solo lectura.** Cada consulta corre dentro de una transaccion ``READ ONLY`` y el servicio
  nunca escribe en la base. La deduplicacion vive en el SQL (ventanas de tiempo), no en una
  marca persistida.
* **Silencio cuando esta todo bien.** Si ningun vigilante da mas de 0, no hay mensaje que
  mandar. Avisar todos los dias de "todo bien" entrena a ignorar el aviso.
* **Una falla propia no se calla.** Si una consulta se rompe, sale como "no pude revisar",
  nunca como "todo bien": un vigilante muerto no puede parecerse a un vigilante tranquilo.

Las consultas viven en ``audit/vigilantes.sql`` — fuente unica: el informe de auditoria y este
servicio leen el mismo archivo, asi que un chequeo nuevo se agrega en un solo lugar.

El mensaje al usuario lo compone este servicio y **nunca nombra tablas**: la duena lee que dejo
de pasar, donde se nota y que hacer.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("diana.application")

#: Fuente unica de las consultas (el mismo archivo que documenta el informe de auditoria).
VIGILANTES_SQL_PATH = Path(__file__).resolve().parents[3] / "audit" / "vigilantes.sql"

# Formato de cada bloque del SQL:  -- V<n> | activo|no-activado | <contrato> | <que vigila>
_CABECERA = re.compile(r"^--\s*(V\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$")

#: Vigilantes cuyas filas hay que cruzar con las sesiones de sandbox. El sandbox no persiste
#: a proposito (AGENTS.md §4.20), asi que sus turnos no dejan fila: sin este filtro, cada
#: prueba de la duena en el sandbox dispararia una falsa alarma.
VIGILANTES_CON_FILTRO_SANDBOX = frozenset({"V2"})

#: Cuantas filas de un mismo vigilante se listan antes de resumir el resto.
MAX_FILAS_EN_MENSAJE = 10


class SandboxTurnClassifier(Protocol):
    """Devuelve los turnos que el sandbox no persiguio a proposito.

    Levanta si no puede clasificar: sin poder distinguir una prueba de un turno real, esas
    filas no se pueden juzgar, y callarse seria peor que avisar que no se pudo revisar.
    """

    async def __call__(self, hours: int) -> set[str]: ...


@dataclass(frozen=True, slots=True)
class WatchdogAlert:
    """Un vigilante con filas en alerta."""

    vigilante_id: str
    titulo: str
    contrato: str
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class WatchdogFailure:
    """Un vigilante que no se pudo evaluar (consulta rota, sin clasificador, etc.)."""

    vigilante_id: str
    titulo: str
    error: str


@dataclass(frozen=True, slots=True)
class WatchdogReport:
    """Resultado de una corrida completa."""

    alerts: tuple[WatchdogAlert, ...] = ()
    failures: tuple[WatchdogFailure, ...] = ()
    skipped_sandbox: int = 0

    @property
    def total(self) -> int:
        """Cuantas cosas hay para revisar (una fila en alerta o una falla, una cada una)."""
        return sum(len(a.rows) for a in self.alerts) + len(self.failures)

    @property
    def ok(self) -> bool:
        """True solo cuando no hay nada que avisar (silencio)."""
        return not self.alerts and not self.failures

    def as_dict(self) -> dict[str, Any]:
        """Vista serializable (la usan el latido y el modo seco)."""
        return {
            "alerts": {
                a.vigilante_id: {"titulo": a.titulo, "filas": len(a.rows)} for a in self.alerts
            },
            "failures": {f.vigilante_id: f.error for f in self.failures},
            "skipped_sandbox": self.skipped_sandbox,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class _Copy:
    """Como se cuenta un vigilante en el mensaje (que paso, desde cuando, que hacer)."""

    titulo: str
    que_paso: str
    ventana: str
    que_hacer: str


#: Copia al usuario por vigilante. Si falta, se usa el titulo del SQL y el volcado generico.
_COPY: dict[str, _Copy] = {
    "V1": _Copy(
        titulo="Quedo guardado sin huella",
        que_paso=(
            "Quedaron registros nuevos guardados sin la huella que permite encontrarlos por "
            "parecido (el problema de agosto)."
        ),
        ventana="los ultimos 2 dias",
        que_hacer="Avisame: hay que regenerar esas huellas (lo hace el equipo).",
    ),
    "V2": _Copy(
        titulo="Dejo de registrarse lo que Diana habria decidido sola",
        que_paso="Dejo de quedar el registro de lo que Diana habria decidido sola.",
        ventana="los ultimos 2 dias",
        que_hacer=(
            "Avisame: sin ese registro no hay con que medir si Diana ya puede contestar sola."
        ),
    ),
    "V3": _Copy(
        titulo="Hay intercambios sin tu decision registrada",
        que_paso="Hay intercambios entregados o escalados donde no quedo registrada tu decision.",
        ventana="los ultimos 2 dias",
        que_hacer="Revisa si aprobaste o corregiste esos dias; si te suena, avisame.",
    ),
    "V7": _Copy(
        titulo="Lo que decides no quedo guardado",
        que_paso="Aprobaste o corregiste y tu decision no quedo guardada (el defecto de septiembre).",
        ventana="los ultimos 2 dias",
        que_hacer="Avisame: es el defecto de septiembre y hay que mirarlo ya.",
    ),
}

#: Nombre de negocio de cada dato del chequeo de huellas. El mensaje NUNCA nombra tablas.
_DATO_EN_NEGOCIO: dict[str, str] = {
    "examples": "lo que Diana aprende de tus correcciones",
    "policies": "las reglas del negocio",
    "memories": "los recuerdos de cada VIP",
    "profiles": "las fichas de tus VIP",
    "contexts": "el estado del dia de cada chat",
}

#: Familias de fallos internos del bot, en palabras de negocio. El orden importa: gana el
#: primer prefijo que coincida. Se escriben como titulares para que la linea se lea bien con
#: cualquier cantidad ("Avisos que no te llegaron: 1").
_FAMILIAS_SWALLOWED: tuple[tuple[str, str], ...] = (
    ("owner_notify_failed", "Avisos tuyos que no te llegaron"),
    ("atencion_payment_intent_notified", "Avisos de pago en Atencion que no salieron"),
    ("atencion_doctrine", "Avisos de doctrina en Atencion que no salieron"),
    ("recontact_", "Recontactos que no se pudieron programar o cancelar"),
    ("approval_ui", "Botones de aprobacion que no se pudieron limpiar"),
    ("supersede_", "Cierres de intercambios viejos que no se completaron"),
    ("memory_extraction", "Recuerdos que no se pudieron extraer"),
    ("context_store", "Estados del dia que no se pudieron guardar"),
    ("mood_engine", "Lecturas de animo que fallaron"),
    ("trust_budget", "Ajustes de confianza que fallaron"),
    ("outcome_", "Mediciones de resultados que fallaron"),
    ("turn_classifier", "Clasificaciones de mensajes que fallaron"),
    ("profile_synthesis", "Resintesis de fichas que fallaron"),
    ("emotional_detector", "Lecturas del detector emocional que fallaron"),
)


def leer_vigilantes(ruta: Path | None = None) -> list[dict[str, Any]]:
    """Corta ``vigilantes.sql`` por sus cabeceras ``-- V<n> | …``.

    Funcion pura (no toca la base): la usan tanto el chequeo como las pruebas de contrato.
    """
    texto = (ruta or VIGILANTES_SQL_PATH).read_text(encoding="utf-8")
    vigilantes: list[dict[str, Any]] = []
    for bloque in re.split(r"(?m)^(?=--\s*V\d+\s*\|)", texto):
        lineas = bloque.splitlines()
        if not lineas:
            continue
        cabecera = _CABECERA.match(lineas[0].strip())
        if not cabecera:
            continue
        cuerpo = "\n".join(
            linea for linea in lineas[1:] if not linea.strip().startswith("--")
        ).strip().rstrip(";").strip()
        if not cuerpo:
            continue
        vigilantes.append(
            {
                "id": cabecera.group(1),
                "activo": cabecera.group(2).strip() == "activo",
                "contrato": cabecera.group(3).strip(),
                "titulo": cabecera.group(4).strip(),
                "sql": cuerpo,
            }
        )
    return vigilantes


def _familia_swallowed(evento: str) -> str:
    """Traduce el nombre tecnico de un fallo interno a una familia de negocio."""
    for prefijo, etiqueta in _FAMILIAS_SWALLOWED:
        if evento.startswith(prefijo):
            return etiqueta
    if evento.endswith("_error") or evento.endswith("_failed"):
        return "Piezas del intercambio que fallaron y siguieron solas"
    return "Fallos internos sin clasificar"


def lineas_swallowed(delta: Mapping[str, int]) -> list[str]:
    """Resume los fallos internos que crecieron desde el chequeo anterior, en palabras de negocio."""
    por_familia: Counter[str] = Counter()
    for evento, cuantos in delta.items():
        if cuantos > 0:
            por_familia[_familia_swallowed(evento)] += int(cuantos)
    return [f"{etiqueta}: {cuantos}" for etiqueta, cuantos in por_familia.most_common()]


def clave_de_alerta(vigilante_id: str, fila: Mapping[str, Any]) -> str | None:
    """Identidad de un caso, para no volver a avisarlo manana.

    Los vigilantes que listan intercambios traen el id del turno: ese id no se repite nunca,
    asi que es una identidad segura. Los que resumen por dato (V1) no la tienen y se quedan
    con la ventana de tiempo del SQL como unico tope.
    """
    turno = fila.get("turno")
    return f"{vigilante_id}:{turno}" if turno else None


def filtrar_ya_avisados(report: WatchdogReport, avisados: Collection[str]) -> WatchdogReport:
    """Quita las filas cuyo caso ya se aviso en la corrida anterior.

    La ventana del SQL acota la repeticion; esto la elimina para los casos con identidad
    propia. Un caso que sigue roto no vuelve a sonar todos los dias, y uno nuevo si.
    """
    if not avisados:
        return report
    conocidos = set(avisados)
    alertas: list[WatchdogAlert] = []
    for alerta in report.alerts:
        filas = tuple(
            fila
            for fila in alerta.rows
            if (clave := clave_de_alerta(alerta.vigilante_id, fila)) is None
            or clave not in conocidos
        )
        if filas:
            alertas.append(
                WatchdogAlert(
                    vigilante_id=alerta.vigilante_id,
                    titulo=alerta.titulo,
                    contrato=alerta.contrato,
                    rows=filas,
                )
            )
    return WatchdogReport(
        alerts=tuple(alertas),
        failures=report.failures,
        skipped_sandbox=report.skipped_sandbox,
    )


def claves_avisadas(report: WatchdogReport) -> list[str]:
    """Las identidades que esta corrida acaba de avisar (se guardan en el latido)."""
    claves = [
        clave
        for alerta in report.alerts
        for fila in alerta.rows
        if (clave := clave_de_alerta(alerta.vigilante_id, fila)) is not None
    ]
    return sorted(claves)


class ContractWatchdogService:
    """Corre los vigilantes activos de ``audit/vigilantes.sql`` y compone el aviso.

    La deduplicacion es del SQL (ventanas de tiempo), no del servicio: asi el chequeo entero
    se queda en solo lectura sobre la base.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        sandbox_turns: SandboxTurnClassifier | None = None,
        sql_path: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._sandbox_turns = sandbox_turns
        self._sql_path = sql_path

    async def revisar(self) -> WatchdogReport:
        """Corre cada vigilante activo. Nunca propaga: una consulta rota es una falla mas."""
        vigilantes = [v for v in leer_vigilantes(self._sql_path) if v["activo"]]
        activos = ", ".join(v["id"] for v in vigilantes)
        logger.info(
            "contract_watchdog_run_started",
            extra={"vigilantes": len(vigilantes), "ids": activos},
        )

        avisos: list[WatchdogAlert] = []
        fallas: list[WatchdogFailure] = []
        descartados = 0
        sandbox: set[str] | None = None

        async with self._session_factory() as session:
            for vigilante in vigilantes:
                try:
                    filas = await self._correr(session, vigilante["sql"])
                except Exception as exc:  # noqa: BLE001 — una consulta rota no puede pasar por "todo bien"
                    logger.exception(
                        "contract_watchdog_query_failed", extra={"vigilante": vigilante["id"]}
                    )
                    fallas.append(
                        WatchdogFailure(
                            vigilante_id=vigilante["id"],
                            titulo=vigilante["titulo"],
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    continue

                if vigilante["id"] in VIGILANTES_CON_FILTRO_SANDBOX:
                    if self._sandbox_turns is None:
                        fallas.append(
                            WatchdogFailure(
                                vigilante_id=vigilante["id"],
                                titulo=vigilante["titulo"],
                                error="sin clasificador de sesiones de prueba",
                            )
                        )
                        continue
                    if sandbox is None:
                        try:
                            sandbox = await self._sandbox_turns(48)
                        except Exception as exc:  # noqa: BLE001
                            # Sin poder clasificar, sus filas no se pueden juzgar: se informa
                            # como falla en vez de contar el sandbox como alerta. Los otros
                            # vigilantes siguen corriendo.
                            fallas.append(
                                WatchdogFailure(
                                    vigilante_id=vigilante["id"],
                                    titulo=vigilante["titulo"],
                                    error=f"no pude clasificar las sesiones de prueba: {exc}",
                                )
                            )
                            sandbox = None
                            continue
                    antes = len(filas)
                    filas = [f for f in filas if str(f.get("turno")) not in sandbox]
                    descartados += antes - len(filas)

                en_alerta = tuple(f for f in filas if int(f.get("alerta") or 0) > 0)
                logger.info(
                    "contract_watchdog_checked",
                    extra={
                        "vigilante": vigilante["id"],
                        "alertas": len(en_alerta),
                        "filas": len(filas),
                    },
                )
                if en_alerta:
                    avisos.append(
                        WatchdogAlert(
                            vigilante_id=vigilante["id"],
                            titulo=vigilante["titulo"],
                            contrato=vigilante["contrato"],
                            rows=en_alerta,
                        )
                    )

        report = WatchdogReport(
            alerts=tuple(avisos), failures=tuple(fallas), skipped_sandbox=descartados
        )
        logger.info("contract_watchdog_run_complete", extra=report.as_dict())
        return report

    @staticmethod
    async def _correr(session: AsyncSession, sql: str) -> list[Mapping[str, Any]]:
        """Ejecuta una consulta de vigilancia dentro de una transaccion READ ONLY."""
        async with session.begin():
            await session.execute(sql_text("SET TRANSACTION READ ONLY"))
            resultado = await session.execute(sql_text(sql))
            return resultado.mappings().all()

    def componer_mensaje(
        self,
        report: WatchdogReport,
        *,
        swallowed_delta: Mapping[str, int] | None = None,
    ) -> str | None:
        """Arma el aviso en lenguaje de negocio, o ``None`` si no hay nada que avisar."""
        if report.ok:
            return None

        lineas = [f"🔎 Vigilancia Diana — {report.total} cosa(s) para revisar", ""]
        for alerta in report.alerts:
            contrato = f" ({alerta.contrato})" if alerta.contrato else ""
            lineas.append(f"• {self._titulo(alerta)}{contrato}")
            copy = _COPY.get(alerta.vigilante_id)
            if copy:
                lineas.append(f"  Que paso: {copy.que_paso}")
            for fila in alerta.rows[:MAX_FILAS_EN_MENSAJE]:
                lineas.append(f"  - {self._detalle(alerta.vigilante_id, fila)}")
            if len(alerta.rows) > MAX_FILAS_EN_MENSAJE:
                lineas.append(f"  - y {len(alerta.rows) - MAX_FILAS_EN_MENSAJE} mas")
            if copy:
                lineas.append(f"  Desde cuando: {copy.ventana}.")
                lineas.append(f"  Que hacer: {copy.que_hacer}")
            lineas.append("")

        for falla in report.failures:
            lineas.append(f"⚠️ No pude revisar: {falla.titulo}. ({falla.error})")

        resumen = lineas_swallowed(swallowed_delta or {})
        lineas.append("")
        lineas.append("Fallos internos del bot desde el chequeo anterior:")
        if resumen:
            lineas.extend(f"- {linea}" for linea in resumen)
        else:
            lineas.append("- ninguno")

        if report.skipped_sandbox:
            lineas.append("")
            lineas.append(
                f"(Descarte {report.skipped_sandbox} intercambio(s) de sesiones de prueba: "
                "no se guardan a proposito.)"
            )
        lineas.append("")
        lineas.append("Detalle tecnico: runtime/contract_watchdog.json")
        return "\n".join(lineas)

    @staticmethod
    def _titulo(alerta: WatchdogAlert) -> str:
        copy = _COPY.get(alerta.vigilante_id)
        return copy.titulo if copy else alerta.titulo

    @staticmethod
    def _detalle(vigilante_id: str, fila: Mapping[str, Any]) -> str:
        """Una fila en alerta, en palabras de negocio (nunca el nombre de una tabla)."""
        if vigilante_id == "V1":
            dato = _DATO_EN_NEGOCIO.get(str(fila.get("tabla")), "un dato interno")
            cuantos = fila.get("alerta")
            historico = fila.get("historico")
            return f"{dato}: {cuantos} sin huella (antes habia {historico})"
        cuando = fila.get("cuando")
        if cuando:
            return f"un intercambio del {cuando}"
        return " · ".join(f"{clave}={valor}" for clave, valor in fila.items() if clave != "alerta")


__all__ = [
    "ContractWatchdogService",
    "VIGILANTES_SQL_PATH",
    "WatchdogAlert",
    "WatchdogFailure",
    "WatchdogReport",
    "clave_de_alerta",
    "claves_avisadas",
    "filtrar_ya_avisados",
    "leer_vigilantes",
    "lineas_swallowed",
]

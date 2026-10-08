#!/usr/bin/env python3
"""Vigilantes E4 — chequeo diario de que los efectos prometidos siguen ocurriendo.

Por qué existe: una prueba en verde dice que el efecto ocurría **el día que se
midió**. Si mañana una pieza se desconecta (una bandera que se apaga, un upsert
que vuelve a pisar una columna, el motor de huellas que devuelve ceros), nada
avisa: el producto sigue funcionando y el registro deja de existir en silencio.
Este script es el que avisa.

Qué hace, una vez por día (cron de usuario):

1. Corre las consultas de ``audit/vigilantes.sql`` — solo lectura, cada una
   dentro de una transacción READ ONLY.
2. Suma la columna ``alerta`` de cada vigilante activo.
3. Si algo da más de 0, manda UN mensaje a la dueña por Telegram, en lenguaje
   de negocio, diciendo qué dejaría de estar pasando.
4. Si todo da 0, no manda nada (silencio) y deja la línea de latido en el log.

Decisión de producto detrás del silencio: avisar todos los días de "todo bien"
entrena a ignorar el aviso. El precio es que el silencio no distingue "todo
bien" de "el vigilante no corrió"; por eso cada corrida deja su línea en
``runtime/vigilantes.log`` y una falla del propio vigilante (base inalcanzable,
consulta rota, journal ilegible) SÍ manda mensaje: un vigilante muerto no puede
parecerse a un vigilante tranquilo.

Dos filtros que no se pueden expresar en SQL y por eso viven aquí:

* **Sesiones de sandbox** (§4.20 de AGENTS.md): no persisten a propósito, así que
  sus turnos no dejan fila de sombra. El motivo queda en el journal como
  ``post_turn_skipped_sandbox turn_id=…`` y aquí se descartan esos turnos. Sin
  este filtro, cada prueba de la dueña en el sandbox dispararía una falsa alarma.
* **Salidas del sandbox del reporte**: no aplica; las filas descartadas se
  informan en el log, nunca en el mensaje.

Uso::

    venv/bin/python scripts/vigilantes.py --dry-run   # muestra, no manda nada
    venv/bin/python scripts/vigilantes.py             # corre y avisa si hace falta
    venv/bin/python scripts/vigilantes.py --avisar-activacion   # aviso de puesta en marcha (una vez)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
SQL_PATH = ROOT / "audit" / "vigilantes.sql"

# Turnos que el sandbox se saltó a propósito: se descartan de estos vigilantes.
VIGILANTES_CON_FILTRO_SANDBOX = {"V2"}

# Cómo se lee cada vigilante en el mensaje. Si falta, se usa el volcado genérico.
LINEA_DE_ALERTA: dict[str, str] = {
    "V1": "{tabla}: {alerta} nueva(s) en cero (histórico: {historico})",
    "V2": "chat {chat} · turno {turno} · {estado} · {cuando}",
    "V7": "chat {chat} · turno {turno} · {cuando}",
}

# Qué pierde el negocio si el vigilante se enciende. Es lo único que la dueña
# necesita leer para decidir si hay que actuar.
SIGNIFICADO: dict[str, str] = {
    "V1": (
        "Lo que Diana guarda queda con la huella vacía: existe, pero la búsqueda "
        "por parecido no lo encuentra (el problema de agosto)."
    ),
    "V2": (
        "El registro de lo que Diana habría decidido sola dejó de escribirse: sin "
        "eso no hay con qué medir si ya puede ir sola."
    ),
    "V7": (
        "Lo que tú decides no quedó guardado: el sistema está comparando Diana "
        "contra la nada (el defecto del 10 de septiembre)."
    ),
}

# Aviso de puesta en marcha: se manda UNA vez, a mano, cuando la vigilancia se
# activa o se reinstala (p. ej. al cambiar de cuenta o de máquina). No es parte
# de la corrida diaria: el día a día solo escribe si algo dejó de funcionar.
AVISO_ACTIVACION = (
    "✅ Vigilancia diaria activada\n"
    "\n"
    "Desde hoy reviso sola, una vez por día, tres cosas, y te escribo SOLO si algo "
    "dejó de funcionar:\n"
    "• que lo que Diana guarda no quede con la huella vacía (el problema de agosto);\n"
    "• que cada turno de un VIP siga dejando el registro de lo que Diana habría "
    "decidido sola;\n"
    "• que lo que apruebas o corriges quede guardado (el defecto de septiembre).\n"
    "\n"
    "Si no hay novedades, no te escribo: el silencio significa que está todo en orden.\n"
    'Probé la alarma a propósito y suena (incluida la de "no pude revisar").'
)

_CABECERA = re.compile(r"^--\s*(V\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$")


def _env(clave: str) -> str:
    """Lee una clave del .env (mismo criterio que el resto de scripts/)."""
    for linea in ENV_PATH.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, _, v = linea.partition("=")
        if k.strip() == clave:
            return v.strip().strip('"').strip("'")
    raise KeyError(f"{clave} no está en {ENV_PATH}")


def _conexion() -> tuple[str, str]:
    """(dsn, modo ssl) — asyncpg no acepta `?ssl=` dentro de la URL."""
    url = _env("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://")
    partes = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(partes.query))
    return urllib.parse.urlunparse(partes._replace(query="")), params.get("ssl", "prefer")


def leer_vigilantes(ruta: Path = SQL_PATH) -> list[dict[str, Any]]:
    """Corta ``vigilantes.sql`` por sus cabeceras `-- V<n> | …`."""
    texto = ruta.read_text()
    vigilantes: list[dict[str, Any]] = []
    for bloque in re.split(r"(?m)^(?=--\s*V\d+\s*\|)", texto):
        primera = bloque.splitlines()[0] if bloque.splitlines() else ""
        m = _CABECERA.match(primera.strip())
        if not m:
            continue
        cuerpo = "\n".join(
            ln
            for ln in bloque.splitlines()[1:]
            if not ln.strip().startswith("--")
        )
        cuerpo = cuerpo.strip().rstrip(";").strip()
        if not cuerpo:
            continue
        vigilantes.append(
            {
                "id": m.group(1),
                "activo": m.group(2).strip() == "activo",
                "contrato": m.group(3).strip(),
                "titulo": m.group(4).strip(),
                "sql": cuerpo,
            }
        )
    return vigilantes


def turnos_saltados_por_sandbox(horas: int = 48) -> set[str]:
    """Turnos que el sandbox no persistió a propósito, según el journal del bot.

    Falla ruidosamente: si no se puede clasificar, el vigilante de la sombra
    tiene que decir "no pude revisar", nunca callarse.
    """
    entorno = dict(os.environ)
    entorno.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        salida = subprocess.run(
            [
                "journalctl",
                "--user",
                "-u",
                "diana-bot",
                "--since",
                f"-{horas} hours",
                "-o",
                "cat",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env=entorno,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"no pude leer el journal del bot: {exc}") from exc
    if salida.returncode != 0:
        raise RuntimeError(f"journalctl falló: {salida.stderr.strip()[:300]}")
    return set(re.findall(r"post_turn_skipped_sandbox turn_id=([0-9a-f-]{36})", salida.stdout))


def _linea(vigilante: dict[str, Any], fila: dict[str, Any]) -> str:
    plantilla = LINEA_DE_ALERTA.get(vigilante["id"])
    if plantilla:
        try:
            return "• " + plantilla.format(**fila)
        except KeyError:
            pass
    return "• " + " · ".join(f"{k}={v}" for k, v in fila.items() if k != "alerta")


def componer_mensaje(
    avisos: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    fallas: list[str],
    descartados: int,
) -> str:
    total = sum(len(filas) for _, filas in avisos) + len(fallas)
    lineas = [f"🔎 Vigilancia Diana — {total} cosa(s) para revisar", ""]
    for vigilante, filas in avisos:
        lineas.append(f"{vigilante['id']} · {vigilante['titulo']} ({vigilante['contrato']})")
        lineas.extend(_linea(vigilante, f) for f in filas[:10])
        if len(filas) > 10:
            lineas.append(f"• …y {len(filas) - 10} más")
        significado = SIGNIFICADO.get(vigilante["id"])
        if significado:
            lineas.append(f"Qué significa: {significado}")
        lineas.append("")
    for falla in fallas:
        lineas.append(f"⚠️ No pude revisar: {falla}")
    if descartados:
        lineas.append(
            f"(Descarté {descartados} turno(s) de sesiones de sandbox: no persisten a propósito.)"
        )
    lineas.append("Detalle técnico: runtime/vigilantes.log")
    return "\n".join(lineas)


def avisar(texto: str, *, dry_run: bool) -> None:
    if dry_run:
        print("--- mensaje que se mandaría ---")
        print(texto)
        print("--- (dry-run: no se mandó nada) ---")
        return
    token = _env("TELEGRAM_BOT_TOKEN")
    destino = _env("OWNER_TELEGRAM_ID")
    datos = json.dumps({"chat_id": destino, "text": texto}).encode()
    peticion = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=datos,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:  # noqa: S310
        if respuesta.status != 200:
            raise RuntimeError(f"Telegram respondió {respuesta.status}")


async def revisar(vigilantes: list[dict[str, Any]]) -> tuple[list, list[str], int]:
    url, ssl = _conexion()
    avisos: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    fallas: list[str] = []
    descartados = 0
    sandbox: set[str] | None = None

    conexion = await asyncpg.connect(url, ssl=ssl, timeout=30)
    try:
        for vigilante in vigilantes:
            if not vigilante["activo"]:
                continue
            try:
                async with conexion.transaction(readonly=True):
                    filas = [dict(f) for f in await conexion.fetch(vigilante["sql"])]
            except Exception as exc:  # noqa: BLE001 — una consulta rota no puede pasar por "todo bien"
                fallas.append(f"{vigilante['id']} ({vigilante['titulo']}): {type(exc).__name__}: {exc}")
                continue
            if vigilante["id"] in VIGILANTES_CON_FILTRO_SANDBOX:
                if sandbox is None:
                    try:
                        sandbox = turnos_saltados_por_sandbox()
                    except Exception as exc:  # noqa: BLE001
                        # Sin poder clasificar, sus filas no se pueden juzgar: se
                        # informa como falla en vez de contar sandbox como alerta.
                        # (Los otros vigilantes siguen corriendo.)
                        fallas.append(f"{vigilante['id']} sin clasificar sandbox: {exc}")
                        sandbox = None
                        continue
                antes = len(filas)
                filas = [f for f in filas if str(f.get("turno")) not in sandbox]
                descartados += antes - len(filas)
            alerta = [f for f in filas if int(f.get("alerta") or 0) > 0]
            print(
                f"[{vigilante['id']}] {vigilante['titulo']}: "
                f"{len(alerta)} alerta(s) en {len(filas)} fila(s)"
            )
            if alerta:
                avisos.append((vigilante, alerta))
    finally:
        await conexion.close()
    return avisos, fallas, descartados


async def principal(argumentos: argparse.Namespace) -> int:
    vigilantes = leer_vigilantes()
    activos = [v for v in vigilantes if v["activo"]]
    print(
        f"vigilantes: {len(vigilantes)} leídos, {len(activos)} activos "
        f"({', '.join(v['id'] for v in activos)})"
    )
    try:
        avisos, fallas, descartados = await revisar(vigilantes)
    except Exception as exc:  # noqa: BLE001 — morir callado es el peor resultado
        avisar(f"⚠️ La vigilancia de Diana no pudo correr: {type(exc).__name__}: {exc}", dry_run=argumentos.dry_run)
        print(f"FALLA: {exc}", file=sys.stderr)
        return 1

    if not avisos and not fallas:
        print(f"todo en orden — 0 alertas (sandbox descartados: {descartados})")
        return 0

    mensaje = componer_mensaje(avisos, fallas, descartados)
    avisar(mensaje, dry_run=argumentos.dry_run)
    print(f"AVISOS: {sum(len(f) for _, f in avisos)} alerta(s), {len(fallas)} falla(s)")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="muestra el mensaje sin mandarlo")
    parser.add_argument(
        "--avisar-activacion",
        action="store_true",
        help="manda el aviso de puesta en marcha (una vez, al activar la vigilancia)",
    )
    argumentos = parser.parse_args()
    if argumentos.avisar_activacion:
        avisar(AVISO_ACTIVACION, dry_run=argumentos.dry_run)
        estado = "dry-run" if argumentos.dry_run else "enviado"
        print(f"aviso de activación: {estado}")
        return
    sys.exit(asyncio.run(principal(argumentos)))


if __name__ == "__main__":
    main()

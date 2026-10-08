"""Turnos que el sandbox no persiguio a proposito, leidos del journal del bot.

El sandbox no escribe memorias, ejemplos ni registro de sombra (§4.20 de AGENTS.md), asi que
sus turnos dejan un hueco **por diseno**. El bot lo deja dicho en el journal con el evento
``post_turn_skipped_sandbox turn_id=…``; esta pieza lee esa lista para que el vigilante de la
sombra no cuente como falla lo que fue una prueba de la duena.

Se lee el journal (no la base) porque las sesiones de sandbox son estado del proceso: un
reinicio las pierde, y el turno ya quedo guardado. El journal los recuerda mientras dure su
retencion, que cubre de sobra la ventana de 2 dias de los vigilantes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess

logger = logging.getLogger("diana.infrastructure")

#: Marca que deja el orquestador cuando el sandbox se salta la persistencia.
_PATRON = re.compile(r"post_turn_skipped_sandbox turn_id=([0-9a-fA-F-]{36})")

#: Tope de la propia lectura del journal (no de la ventana consultada).
_TIMEOUT_S = 120


def read_sandbox_turn_ids(hours: int = 48) -> set[str]:
    """Lee del journal los turnos que el sandbox se salto. **Bloqueante.**

    Levanta si no puede leer o clasificar: quien la llame tiene que poder decir "no pude
    revisar" en vez de dar por bueno lo que no vio. Desde el proceso del bot, llamarla con
    ``asyncio.to_thread`` (el ``journalctl`` bloquea).
    """
    entorno = dict(os.environ)
    entorno.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        salida = subprocess.run(  # noqa: S603 — binario fijo, sin shell
            [
                "journalctl",
                "--user",
                "-u",
                "diana-bot",
                "--since",
                f"-{int(hours)} hours",
                "-o",
                "cat",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            env=entorno,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"no pude leer el journal del bot: {exc}") from exc
    if salida.returncode != 0:
        raise RuntimeError(f"journalctl fallo: {salida.stderr.strip()[:300]}")
    return set(_PATRON.findall(salida.stdout))


class JournalSandboxTurnClassifier:
    """Clasificador asincrono: corre la lectura del journal fuera del bucle de eventos.

    Es lo que se inyecta al vigilante. El bucle del bot no se bloquea esperando al journal,
    aunque la lectura tarde.
    """

    def __init__(self, *, timeout_s: float | None = None) -> None:
        self._timeout_s = timeout_s

    async def __call__(self, hours: int = 48) -> set[str]:
        llamada = asyncio.to_thread(read_sandbox_turn_ids, hours)
        if self._timeout_s is None:
            return await llamada
        return await asyncio.wait_for(llamada, timeout=self._timeout_s)


__all__ = ["JournalSandboxTurnClassifier", "read_sandbox_turn_ids"]

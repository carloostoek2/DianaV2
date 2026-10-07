---
name: contract-proof
description: Verifica con pruebas REALES que lo que el sistema promete (contratos de specs, wiki, anexos) es lo que realmente se ejecuta, no solo que el código exista. Úsala siempre que se hable de auditar contratos, verificar cableado, comprobar que una función "de verdad corre", revisar que el modo sombra, los embeddings, la memoria, el historial, el aprendizaje o cualquier función núcleo estén conectados, o cuando algo "debería estar implementado" pero no hay evidencia de efecto. También cuando alguien diga "se implementó pero no funcionaba", "está detrás de una bandera", "las pruebas pasan pero en producción no pasa nada".
---

# contract-proof — de "está escrito" a "está ocurriendo"

## Principio
Un contrato **no está verificado** porque exista código o porque una prueba unitaria con piezas simuladas pase.
Está verificado solo si se demuestra, con el sistema real, que **el efecto prometido ocurre** y que **deja de ocurrir si se desconecta la pieza**.

## Los 3 niveles de evidencia (cada contrato recibe uno)
| Nivel | Qué prueba | Vale como "cumple" |
|---|---|---|
| E0 | Existe código y doc | NO |
| E1 | Prueba unitaria con simulados (`InMemory*`, `FakeLLM`) | NO (solo prueba la pieza aislada) |
| E2 | Flujo real desde la entrada hasta una fila/mensaje en Postgres real, sin simular la pieza bajo prueba | Casi |
| E3 | E2 + **sabotaje**: al desconectar la pieza la prueba falla | **SÍ** |
| E4 | E3 + vigilante en producción que alerta si el efecto deja de ocurrir | Ideal |

Regla dura: **solo E3 o E4 se reporta como ✅**. E0/E1 se reporta como "sin verificar".

## Flujo (por contrato)
1. **Extraer** el contrato → `references/contract-template.md`. Una promesa, un efecto observable, una fuente (doc + sección).
2. **Rastrear** el camino real: entrada (mensaje/job/comando) → … → efecto. Anotar cada punto donde la cadena puede romperse en silencio (banderas, dependencias `None`, `except Exception`, "disabled" solo en log). Herramienta: `python audit/tools/wiring_scan.py`.
3. **Probar** con efecto real → `references/proof-patterns.md`. Reutilizar fixtures de `tests/e2e` (testcontainers + Postgres). Prohibido simular el componente que el contrato promete.
4. **Sabotear** → `references/sabotage-playbook.md`. Desconectar a propósito y exigir que la prueba falle. Si no falla, la prueba es decorativa: reescribirla.
5. **Matriz de banderas**: correr el contrato con cada bandera relevante en ON y OFF; el contrato debe declarar qué efecto se espera en cada estado (incluido "ninguno, por diseño").
6. **Registrar** el resultado en `audit/contracts/<ID>.md` y en el semáforo.
7. **Proponer vigilante** (E4): una consulta o chequeo diario que detecte que el efecto dejó de ocurrir.

## Patrones de fallo a cazar (los que ya ocurrieron aquí)
- **Pieza opcional que se omite sin ruido:** `if embedder is None: return` / `if self._x is None: return`.
- **Envoltura "best-effort":** `try … except Exception: log_swallowed(...)`. El fallo no rompe nada, tampoco avisa.
- **Apagado solo con log info:** `*_disabled`, `*_skipped`, `no_embedder`.
- **Cableado por bandera:** `x if settings.feature_y else None` en `composition.py`; el flujo existe pero nadie lo recibe.
- **Función huérfana:** definida y probada, nunca llamada desde producción.
- **Prueba que no ve el cableado:** el test construye el servicio a mano en vez de pasar por `build_app`.
- **Upsert que borra lo ya escrito:** `INSERT … ON CONFLICT DO UPDATE` que pisa columnas con NULL (ocurrió: owner_outcome, 23-ago→10-sep).
- **Documentación que afirma de más:** la wiki dice "activa" algo que nadie llama (búsqueda por parecido en `profiles`).
- **Bandera apagada a propósito y sin registrar:** `.env` decía "VIVO", valor real `false`. Toda bandera núcleo apagada debe declarar motivo y fecha.
- **Ruta de diseño que nunca pasa por el registro** (escalación por palabra clave, plantillas, sandbox): un hueco puede ser diseño, no fallo. Clasificar por ruta ANTES de culpar a errores tragados.

## Qué cuenta como prueba válida
- Parte del punto de entrada **real** (handler, job, `build_app`), no del servicio ya armado.
- Aserta sobre **estado persistido** (fila, columna con valor no nulo/no vacío/no por defecto) o salida real, no sobre que "se llamó a un mock".
- Los valores asertados no pueden ser los de relleno (ej. vector de ceros, `None`, `""`).
- Usa un LLM falso **determinista** solo para el modelo de lenguaje externo; todo lo demás es real.

## Cómo reportar a la dueña
Lenguaje de negocio (AGENTS.md §0): qué prometía, si ocurre de verdad, qué pierde el negocio si no, y qué decisión se necesita. Semáforo: 🟢 E3/E4 · 🟡 E2 · 🔴 no ocurre · ⚪ sin verificar. Nada de jerga sin traducir.

## Reglas
- No arreglar código de producción durante la auditoría: se reporta con evidencia y se propone arreglo aparte.
- Una prueba nueva que pasa a la primera es sospechosa: sabotear antes de confiar.
- Si no se puede ejecutar algo (sin Docker, sin credenciales de Telegram), decirlo y marcar ⚪, nunca asumir.

## Lección de la ronda piloto
De 3 hipótesis iniciales (errores tragados en la sombra, causa común en el cambio de cuenta, ceros vivos en perfiles) las 3 resultaron falsas o inocuas al medir. La regla "no concluir sin medir" evitó arreglar lo equivocado. Siempre: hipótesis → medición en datos reales → conclusión marcada (probado / probable / sin determinar).

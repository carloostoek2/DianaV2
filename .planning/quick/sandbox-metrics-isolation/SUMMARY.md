# SUMMARY — sandbox-metrics-isolation

**Item:** sandbox-metrics-isolation — marca durable `turns.is_sandbox` y exclusión del sandbox en métricas/aprendizaje  
**Fecha:** 2026-10-19 (PR #26 mergeado 22:16 hora CDMX)  
**Estado:** COMPLETE  
**Rama:** `fix/sandbox-metrics-isolation`  
**Commit:** `4bc5754` · **PR:** [#26](https://github.com/carloostoek2/DianaV2/pull/26)  
**Detalle técnico:** [AGENTS.md §4.20 — Marca durable `turns.is_sandbox`](../../../AGENTS.md) (no se duplica aquí)

---

## Por qué

El sandbox solo existía en memoria (`sandbox.py`): no quedaba rastro en la DB,
así que todo lector de métricas que leía `turns` y `traces` contaba los turnos
de sandbox como reales. En una ventana de 14 días:

- **5 turnos de sandbox** del VIP `…3bdc` — que también tiene tráfico real —,
  enviados **sin aprobación**, se contaban como aciertos o como conservadoras.
- **5 filas** en `turn_category_log` y **2** en `emotional_signal_log`.
- **1 resíntesis** del perfil disparada por tráfico de sandbox.
- La reacción de confianza (`_run_outcome_reaction`) se contaminaba.

Como el mismo VIP mezcla tráfico real y de prueba, **se filtra por turno y no
por VIP**.

## Qué hace

| Pieza | Cambio |
|-------|--------|
| Migración `037_turns_is_sandbox` | Columna `turns.is_sandbox` `boolean NOT NULL DEFAULT false`, con `lock_timeout` de 5 s |
| `TurnCoordinator` | Fija `is_sandbox` al crear el turno (`sandbox.is_active(chat_id)`) |
| Hooks post-turno | Usan la marca del turno (`_turn_is_sandbox`), no el estado vivo del sandbox |
| `_run_outcome_reaction` | Gate: un turno de sandbox no mueve la confianza |
| `turn_category_log` / `emotional_signal_log` | No se escriben para turnos de sandbox |
| `repositories/sandbox_filters.py` | Helpers únicos aplicados en coincidencia y readiness, señales, síntesis de perfil, métricas, calibración, cognición (mismo modo, `trace_same_sandbox_mode_as`) y staging |
| Vigilantes V2, V3, V4 | `NOT t.is_sandbox` en el SQL; ya no dependen del journal |
| Lectores operativos | **Sin filtro a propósito:** lifecycle, recovery, `/trazas`, `latest_turn_id` |

Sin feature flag: es una corrección (columna con default `false` + filtro de lectura).

## Condiciones del Analista de riesgos

Veredicto: **ADELANTE CON CONDICIONES** — todas cumplidas.

| # | Condición | Estado |
|---|-----------|--------|
| 1 | Gate en `_run_outcome_reaction` | ✅ |
| 2 | Hooks y lectores usan `turn.is_sandbox` | ✅ |
| 3 | Revisión de todos los lectores de `turns` | ✅ |
| 4 | Backfill solo con OK explícito de Juan | ✅ (no se hizo) |
| 5 | `lock_timeout` en la migración | ✅ |

Además: sin flag, por ser corrección.

## Pruebas

| Suite | Resultado |
|-------|-----------|
| Unit | **4500 passed**, 2 skipped |
| audit + e2e (Postgres 16 local) | **301 passed**, 1 xfailed |
| Migración 037 | upgrade → downgrade → upgrade OK |
| ruff | **no se corrió** |

## Despliegue

Ver también [docs/OPS_SINGLE_INSTANCE.md](../../../docs/OPS_SINGLE_INSTANCE.md).

1. `git pull` en la instancia.
2. `alembic upgrade head` **antes** de reiniciar `diana-bot`.
3. Verificar con `alembic heads` (un solo head) y `alembic current` (= 037).
4. Reiniciar `diana-bot`.

**Notas post-deploy:**

- **No hay backfill:** los turnos de sandbox anteriores a la migración quedan
  `false` y siguen contando como reales.
- **V2 puede dar falsas alarmas durante ~48 h** mientras la ventana contiene esos turnos.
- Tras un reinicio con el sandbox activo, la sesión en memoria se pierde y los
  turnos siguientes quedan `is_sandbox=false` hasta reactivar el sandbox.
- **Riesgo de dos heads:** la rama `fix/profile-synthesis-truncation` trae su
  propia `037`; si se mergea después, hay que renumerarla (038, `down_revision`
  = `037_turns_is_sandbox`) antes del deploy.

## Referencias

- Commit `4bc5754` · PR [#26](https://github.com/carloostoek2/DianaV2/pull/26)
- AGENTS.md §4.20 · docs/SPEC-FASE3.md (nota sobre `vips.is_sandbox`)

---
title: Jobs
created: 2026-08-11
updated: 2026-08-16
type: entity
tags: [modulo, operacion, contrato]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Jobs

Tareas periódicas programadas del sistema.

- **Pregunta que responde:** ¿Qué tareas periódicas ejecutar?
- **Puede:** recontacto, purga de trazas, calibración.
- **Nunca puede:** ejecutar lógica cognitiva o de decisión directamente — debe delegar en Application Services.

## Jobs conocidos

- **Recontacto por silencio** (ej. cada hora): `RecontactService.get_due_vips()` + `execute_recontact` (flujo 4.9 de AGENTS.md; ver [[application-services]]).
- **Calibración de umbrales** (ej. domingo 3 AM): `CalibrationService.calibrate_thresholds(window_days=30)` + `detect_drift()` (flujo 4.11).
- **Purga de trazas:** TTL de objetos intermedios (30 días recomendado en Fase 1, configurable).

## Invariantes

- No se programa recontacto si el VIP está congelado, en pausa o con aprobación pendiente (AGENTS.md §4.9).
- La calibración nunca corre dentro del pipeline (AGENTS.md §4.5).
- Jobs → Application Services (dirección de dependencia obligatoria).

## Implementación real (2026-08-11, verificado 2026-08-16)

`jobs/` sigue con **8** jobs (0 archivos nuevos o borrados desde 2026-08-11). Todos envuelven servicios de [[application-services]] (nunca lógica cognitiva directa):

- `recontact.py` — loop periódico de recontacto por silencio.
- `calibration.py` — calibración dual de umbrales + drift.
- `backfill.py` — scheduler de la cola de backfill de perfiles VIP.
- `profile_synthesis_job.py` — escaneo + drenaje + síntesis de perfiles.
- `gray_zone_expiration.py` — expiración de consultas de doctrina obsoletas.
- `metrics.py` — agregación semanal de learning_metrics.
- `trace_purge.py` — purga TTL de pipeline_traces.
- `agent_data_purge.py` — purga TTL de tablas de evolución de agente.

No hay job de [[vinculo-lucien]] ni de [[eventos-temporales]]: el vínculo es middleware + `LinkCoordinator`; los eventos expiran por ventana `[start_at, end_at)` en el augmenter.

^[src/diana/jobs/*, AGENTS.md §2.1]

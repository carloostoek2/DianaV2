---
title: Zona Gris y Políticas
created: 2026-08-11
updated: 2026-08-16
type: concept
tags: [politica, aprendizaje, flujo]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md, ../../src/diana/application/gray_zone_service.py, ../../src/diana/application/turn_orchestrator.py]
confidence: high
---

# Zona Gris y Políticas

La zona gris es el mecanismo para cuando falta una **regla de negocio reutilizable** (doctrina): se consulta a la dueña y la respuesta se **destila** en una política estructurada (REQ-GAP-*).

## Flujo

1. El Analista indica `needs_policy=true` o el Evaluador detecta Doctrina insuficiente — esto es una **observación**, no una decisión (REQ-GAP-01).
2. Si ya existe política aplicable, se reutiliza y no se vuelve a preguntar (REQ-GAP-02). El retriever ve políticas globales más, en un turno VIP, las de ese `vip_id` (ver [[capability-registry]]).
3. Si no hay política, el [[decisor]] decide "Consultar doctrina" (prioridad 2) y el VIP queda **congelado** (sin lectura/typing/envío/recontacto del bot). En Atención (sin `vip_id`) el freeze es la fila abierta de `gray_zone_queries` resuelta por `chat_id`.
4. La dueña responde: doctrina, usar el borrador propuesto, u omitir (REQ-GAP-04).
5. El sistema pide **generalización**: "¿esto aplica siempre que pregunten por X, o solo en este caso?" — sin este paso no se crea la política (REQ-GAP-11).
6. La respuesta se destila a política **estructurada**, nunca literal (REQ-GAP-05, BR-14), y pasa por confirmación explícita antes de quedar activa (`promote_to_policy`, opcionalmente con `vip_id`).
7. Se descongela y el flujo vuelve al camino normal (REQ-GAP-06).

## Paracaídas si falla el aviso a la dueña (F6, 2026-08-16)

`consult_doctrine` crea la query (y congela) **antes** de mandar el DM. Si `send_doctrine_query` lanza:

1. `GrayZoneService.discard_and_close` — cierra la query y descongela.
2. La decisión se degrada a `approve` con `reason=vip_doctrine_notify_failed` (VIP) o `atencion_doctrine_notify_failed` (Atención).
3. El turno pasa a `PENDING_APPROVAL` y la dueña ve el borrador, no un freeze huérfano de 24 h sin DM.

Otros demotes de aplicación (no cambian al Decider): sandbox sin VIP → `sandbox_no_vip_doctrine`; Atención sin flags/servicio → `atencion_no_vip_doctrine`. Si fallan a la vez la entrega supervisada y el fallback de escalate, `reopen_query` puede reabrir una fila `resolved`/`expired` para no dejar el turno en gray_zone muerto.

## Estructura obligatoria de una política (REQ-GAP-10)

`disparador` (tipo de situación, no palabras exactas) + `regla` (qué hacer/decir) + `ejemplo_aplicado` (opcional, contrato de producto; la fila live guarda `trigger_description`, `rule`, `scope`, `valid_until`, `vip_id`) + `alcance` (todos los VIP, un VIP, o segmento) + `vigencia` (expiración opcional).

`vip_id` es eje distinto de `scope`: Atención solo recupera filas globales; un VIP recupera globales + las suyas ([[anti-contaminacion]]).

## Límites

- La zona gris **no** se usa para dudas de tono/estilo (eso es Naturalidad baja → regenerar/aprobar, BR-03).
- Las consultas abiertas expiran tras un tiempo configurable (REQ-GAP-07).
- La función es desactivable por configuración sin romper el resto (REQ-GAP-09).
- Métrica asociada: repetición de la misma pregunta de zona gris → si ocurre, la destilación está fallando (REQ-MET-02).

^[docs/REQUERIMIENTOS.md §9.7, src/diana/application/turn_orchestrator.py consult_doctrine]

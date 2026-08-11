---
title: Zona Gris y Políticas
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [politica, aprendizaje, flujo]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md]
confidence: high
---

# Zona Gris y Políticas

La zona gris es el mecanismo para cuando falta una **regla de negocio reutilizable** (doctrina): se consulta a la dueña y la respuesta se **destila** en una política estructurada (REQ-GAP-*).

## Flujo

1. El Analista indica `needs_policy=true` o el Evaluador detecta Doctrina insuficiente — esto es una **observación**, no una decisión (REQ-GAP-01).
2. Si ya existe política aplicable, se reutiliza y no se vuelve a preguntar (REQ-GAP-02).
3. Si no hay política, el [[decisor]] decide "Consultar doctrina" (prioridad 2) y el VIP queda **congelado** (sin lectura/typing/envío/recontacto del bot).
4. La dueña responde: doctrina, usar el borrador propuesto, u omitir (REQ-GAP-04).
5. El sistema pide **generalización**: "¿esto aplica siempre que pregunten por X, o solo en este caso?" — sin este paso no se crea la política (REQ-GAP-11).
6. La respuesta se destila a política **estructurada**, nunca literal (REQ-GAP-05, BR-14), y pasa por confirmación explícita antes de quedar activa.
7. Se descongela y el flujo vuelve al camino normal (REQ-GAP-06).

## Estructura obligatoria de una política (REQ-GAP-10)

`disparador` (tipo de situación, no palabras exactas) + `regla` (qué hacer/decir) + `ejemplo_aplicado` (opcional) + `alcance` (todos los VIP o segmento) + `vigencia` (expiración opcional).

## Límites

- La zona gris **no** se usa para dudas de tono/estilo (eso es Naturalidad baja → regenerar/aprobar, BR-03).
- Las consultas abiertas expiran tras un tiempo configurable (REQ-GAP-07).
- La función es desactivable por configuración sin romper el resto (REQ-GAP-09).
- Métrica asociada: repetición de la misma pregunta de zona gris → si ocurre, la destilación está fallando (REQ-MET-02).

^[docs/REQUERIMIENTOS.md §9.7]

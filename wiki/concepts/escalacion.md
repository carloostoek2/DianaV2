---
title: Escalación
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [flujo, riesgo, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md]
confidence: high
---

# Escalación

El bot **no** debe cerrar el caso: la dueña (o un humano) toma el hilo (REQ-ESC-*). Hay dos vías de escalación.

## 1. Cortocircuito determinístico (REQ-COG-16, REQ-ESC-01)

Palabras/temas prohibidos (pagos, reclamos, crisis, "eres un bot") disparan la escalación **antes del Analista** — sin costo de LLM y sin riesgo de que el modelo improvise. El VIP no recibe respuesta automática del flujo normal.

## 2. Escalación semántica (REQ-ESC-02)

El Analista puede señalar `risk=alto`, o el Evaluador/[[decisor]] escalan a partir del perfil: seguridad baja (prioridad 1 del Decisor) o `emotion=molesta` (frustración directa, prioridad 2b).

## Ciclo de vida

- La dueña **tria** la escalación: válida, falso positivo, o forzar generación normal (REQ-ESC-04).
- Los falsos positivos se registran para reducir repeticiones indebidas (REQ-ESC-05).
- Queda traza auditable: quién, por qué, veredicto, incluidos los objetos del pipeline (REQ-ESC-06).
- Métrica asociada: tasa de falsos positivos de escalación (REQ-MET-03).

## Jerarquía con la zona gris (BR-02)

La escalación por **seguridad** tiene prioridad absoluta sobre la zona gris. La escalación por **risk semántico** se evalúa después de la zona gris (ver [[decisor]] y [[zona-gris-y-politicas]]).

^[docs/REQUERIMIENTOS.md §9.6]

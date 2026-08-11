---
title: Modos de Operación
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [modo, arquitectura, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md]
confidence: high
---

# Modos de Operación

Los modos son **restricciones externas** al pipeline: el [[decisor]] propone una acción y los modos filtran lo permitido (REQ-COG-10, BR-12).

## Modos globales

- **Supervisado:** ningún envío VIP sin acción de la dueña (aprobar o corregir), salvo excepciones explícitas (REQ-MODE-01). Es el modo recomendado al arrancar.
- **Autónomo:** el sistema envía sin aprobación previa, sujeto al Decisor + perfil de evaluación (REQ-MODE-02). Puede notificar a la dueña según reglas sobre dimensiones bajas (REQ-MODE-07).

## Modos y estados complementarios

- **Sandbox:** mismo pipeline cognitivo completo, solo el Behavior Engine es FakeDelivery (REQ-COG-14, BR-06). No contamina el aprendizaje de producción.
- **Pausa de datos por VIP:** el VIP no recibe automatización ni recontacto (BR-05).
- **Congelación:** mientras hay consulta de zona gris abierta, cero señales del bot hacia el VIP (REQ-GAP-03, REQ-NFR-03).
- **Auto-envío por VIP:** excepción per-VIP aunque el global sea supervisado (REQ-MODE-08).

## Distinción clave (BR-01)

**Aprobación ≠ escalación ≠ zona gris ≠ nota.** Cada una responde una pregunta distinta.

^[docs/REQUERIMIENTOS.md §9.5, §12]

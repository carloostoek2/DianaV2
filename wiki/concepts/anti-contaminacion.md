---
title: Anti-Contaminación
created: 2026-08-11
updated: 2026-08-11
type: concept
tags: [memoria, aprendizaje, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md]
confidence: high
---

# Anti-Contaminación

La Memoria de un VIP es **privada a ese VIP** y **nunca** puede filtrarse al banco de few-shots reutilizables entre VIP (REQ-MEM-07, REQ-TRN-09, REQ-NFR-15, BR-15). Es uno de los cinco principios rectores innegociables del sistema.

## Qué protege

- **Memoria/Perfil/Contexto:** hechos y preferencias de un VIP concreto.
- **Banco de Ejemplos (few-shot):** casos exitosos reutilizables, separados y con reglas de acceso propias.

## Reglas

- Los cinco tipos de conocimiento nunca se mezclan ni se recuperan indiscriminadamente (BR-10).
- Ningún hecho de Memoria se convierte automáticamente en few-shot general.
- El contenido de cualquier tipo de conocimiento se trata como **dato no confiable**, nunca como instrucciones del sistema (REQ-MEM-05).
- En el checklist de revisión: "¿Se mantiene la anti-contaminación Memoria ↔ Ejemplos?" (AGENTS.md §6).

Relacionado: [[aprendizaje-post-turno]], [[capability-registry]].

^[docs/REQUERIMIENTOS.md §9.8, AGENTS.md §1]

---
title: Anti-Contaminación
created: 2026-08-11
updated: 2026-08-16
type: concept
tags: [memoria, aprendizaje, contrato]
sources: [../../docs/REQUERIMIENTOS.md, ../../AGENTS.md, ../../src/diana/infrastructure/db/repositories/examples.py, ../../src/diana/application/staging_service.py]
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

## Bancos con `vip_id` (2026-08-16)

`examples.vip_id` y `policies.vip_id` **no** mezclan Memoria con el banco: son el mismo tipo de conocimiento, acotado a un VIP o global.

Cláusula de visibilidad (ejemplos y políticas):

- Canal Atención / `vip_id is None` → solo filas globales (`column IS NULL`).
- Turno VIP → globales **o** las de ese VIP (`IS NULL OR == vip_id`).
- Un VIP **nunca** ve el banco scoped de otro VIP.

El retriever de examples no importa módulos de memoria (AST gate). El retriever de memoria exige `WHERE vip_id = :vip_id` y no toca `examples`.

## Escritura al banco (Staging / calidad)

- `promote_to_example` inserta un few-shot **global** `quality=standard` (sin `vip_id`).
- Destacar (`insert_gold_example`) inserta `quality=gold` con alcance global o de ese VIP; no requiere candidato de staging, pero **sí** confirmación explícita de la dueña. Flag de escritura: `FEATURE_QUALITY_FEEDBACK_ENABLED`. El retrieval siempre usa `quality`/`vip_id`.
- Reprender → `promote_to_counter_example(vip_id=…)` o `promote_to_policy(vip_id=…)`.
- **REQ-ATN-13:** un candidato del canal `atencion` no puede entrar al banco VIP (`AtencionPromoteBlocked`) — ni gold, ni example, ni contraejemplo.
- EA-05: `stable_traits` / `sensitivities` del [[perfil-evolutivo]] jamás alimentan el banco ni el retriever de examples.

Relacionado: [[aprendizaje-post-turno]], [[capability-registry]], [[zona-gris-y-politicas]].

^[docs/REQUERIMIENTOS.md §9.8, AGENTS.md §1, src/diana/infrastructure/db/repositories/examples.py]

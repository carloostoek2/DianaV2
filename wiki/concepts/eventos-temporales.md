---
title: Eventos temporales
created: 2026-08-16
updated: 2026-08-16
type: concept
tags: [memoria, operacion, regla-negocio]
sources:
  - ../../src/diana/application/ephemeral_event_service.py
  - ../../src/diana/application/ephemeral_knowledge.py
  - ../../alembic/versions/027_ephemeral_events.py
confidence: high
---

# Eventos temporales

Contexto de vida corta que **solo la dueña** escribe para que Diana lo tenga presente un rato (promo del fin de semana, un cumpleaños, un aviso puntual). No es memoria de un VIP ni doctrina permanente. Vive en `ephemeral_events` (migración **027**) y entra al turno como `knowledge.ephemeral`.

No hay feature flag: el augmenter está **siempre** cableado. Si no hay eventos vigentes, el mapa de conocimiento no cambia.

## Quick path

1. Panel de la dueña → **📅 Eventos temporales** ([[superficie-admin]]).
2. «¿Qué le digo a Diana?» + duración (Hoy / 2 días / 3 días / 1 semana / otra fecha).
3. Confirmar. Mientras `start_at ≤ ahora < end_at` y no está pausado, cada turno recibe el texto.
4. Al vencer, Diana deja de verlo sola: no hay job de limpieza.

## Qué puede inyectar la dueña

- **Texto libre** (`body`): lo que Diana debe tener presente.
- **Ventana** `[start_at, end_at)` (semiabierta).
- **Pausar / reanudar** (reversible; pausado = invisible al augmenter).
- **Modificar** texto o fechas (conserva id y pausa).
- **Terminar antes** (`end_at = ahora`) o **eliminar** la fila.

Duraciones que entiende el asistente: `N minutos|horas|días|semanas`, `hoy` (fin del día local), `ahora`, o `YYYY-MM-DD` / `YYYY-MM-DD HH:MM` (naive = zona del servidor). Fechas inválidas se reintentan; no se inventa la ventana.

Los eventos son **globales** (la tabla no tiene `vip_id` ni `channel_type`): aplican a todo turno que pase por el augmenter, VIP o atención.

## Cómo llega al contexto

`EphemeralKnowledgeAugmenter` (capa application, no un retriever del [[capability-registry]]) lee `find_active_at(now)` y, si hay filas, añade una copia del mapa con:

```json
{ "knowledge.ephemeral": { "eventos": ["promo del fin de semana"] } }
```

El [[pipeline-cognitivo]] lo emite al final de los bloques de conocimiento, **cercado** como dato de producto (`<<KNOWLEDGE_EPHEMERAL_DATA>>`, SEC-INJ-02): nunca como instrucción. Si no hay eventos activos, el mapa original se devuelve intacto.

## Qué no puede contaminar

Probado en código; no hay regla de producto extra:

- No escribe `memories`, examples, policies ni staging. El [[aprendizaje-post-turno]] no lo referencia.
- No pisa `knowledge.profile` ni otras claves: solo añade `knowledge.ephemeral`.
- No muta el mapa de entrada (copia superficial si hay hit).
- No mezcla tipos de conocimiento ni cruza VIPs (no es ficha de VIP; ver [[memoria-vip]] / [[anti-contaminacion]]).
- Escrituras solo si `actor_id` es la dueña (`OwnerAuthError` si no).

Relacionado: [[superficie-admin]], [[anti-contaminacion]], [[pipeline-cognitivo]].

^[src/diana/application/ephemeral_event_service.py]
^[src/diana/application/ephemeral_knowledge.py]

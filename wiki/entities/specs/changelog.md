---
title: Changelog
created: 2026-08-11
updated: 2026-08-21
type: entity
tags: [estado, operacion]
sources: [../../CHANGELOG.md]
confidence: high
---

# Changelog

Historial de cambios del sistema (CHANGELOG.md). **Al día: 2026-08-20** (última entrada "Cognitive greeting and delivery polish").

## Saludo cognitivo y pulido de entrega — 2026-08-20

- Entrega en **burbujas por párrafo**: los borradores se dividen por bloques de línea en blanco antes del corte por caracteres; las respuestas multi-párrafo llegan como mensajes separados naturales.
- **Progreso de envío**: entregas multi-segmento muestran a la dueña un indicador "enviando X/Y" en vivo.
- **Quirks de entrega ponderados**: la selección de quirks favorece el error de tipeo + autocorrección y la tasa general sube a 20 %.
- Fix: arranque sin hang en la cola de backfill de memoria — el chequeo de historial usa un `count()` barato en vez de recorrer todo el historial por páginas.

## Control de la dueña, vínculo Lucien y calidad — 2026-08-16

- [[calidad-feedback]]: Destacar/Reprender en borradores VIP; banco gold-first.
- [[vinculo-lucien]]: aviso de expulsión Lucien→Diana.
- [[eventos-temporales]]: contexto con fecha, sin flag.
- Menú unificado, progreso en vivo al aprobar, paracaídas si falla el aviso de doctrina.
- Ops: repo en migración 029; producción verificada hasta 026.

## Evolución de agente (shadow) — 2026-08-07

- Motor de observación completo en modo shadow: señales emocionales, auto-clasificación por turno, mood 3 ejes, trust por VIP (ver [[detector-emocional]], [[perfil-evolutivo]], [[trust-budget]]).
- Eventos de corrección estructurados; purga automática TTL (housekeeping).
- El clasificador pondera contenido sensible/personal primero.

## Funcionalidades acumuladas

- **Memoria automática** y **perfiles VIP** desde el historial ([[memoria-vip]]).
- **Canal de atención** no-VIP con escalación real ([[canal-atencion]]).
- Freeze/pausa de VIP, menú rediseñado, registro de VIP por reenvío.
- Staging con aprobación de la dueña ([[aprendizaje-post-turno]]).
- Dashboard de la dueña (`/resumen`, `/metricas`), trazabilidad paso a paso.
- Ciclo de atención de 30 días + seguimiento proactivo no-VIP.
- Seguimiento autónomo post-respuesta, manejo de mensajes editados, recuperación resiliente tras reinicio, sandbox.

## Mejoras y seguridad

- Historial rápido en conversaciones largas; entrega human-like por modo.
- Español neutro consistente, sin dialecto ni slang (ver [[comunicacion-con-producto]]).
- Seguridad: los errores de memoria no exponen contenido crudo; sanitización de prompts; gates owner-only; canal de atención fail-closed.

## Cambio rompedor

El canal de atención solo admite chats que recibieron la promo y permanece abierto 30 días (el pago lo cierra).

^[CHANGELOG.md]

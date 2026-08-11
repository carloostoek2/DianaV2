---
title: Changelog
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [estado, operacion]
sources: [../../CHANGELOG.md]
confidence: high
---

# Changelog

Historial de cambios del sistema (CHANGELOG.md).

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

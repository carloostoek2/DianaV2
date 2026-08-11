---
title: Application Services
created: 2026-08-11
updated: 2026-08-11
type: entity
tags: [modulo, contrato, flujo]
sources: [../../AGENTS.md, ../../docs/SPEC-1.1.md]
confidence: high
---

# Application Services

Capa de orquestación de casos de uso. Traduce intenciones de la capa Telegram en ejecución de servicios.

- **Pregunta que responde:** ¿Qué caso de uso es este?
- **Puede:** orquestar Orquestador, Admin, Sandbox, Recontacto, Promo, Calibración.
- **Nunca puede:** contener lógica cognitiva, generar texto, evaluar.

## Servicios

- **Turn Orchestrator** — orquestación del turno completo.
- **AdminService** — superficie de administración (allowlist, estado, modo, pausa, staging, métricas; ver REQ-ADM-*).
- **SandboxService** — modo de prueba con FakeDelivery (Fase 2).
- **RecontactService** — `execute_recontact(vip_id)` con pipeline reducido; nunca ejecuta Analista/Planificador; plantillas fijas; respeta congelación/pausa (AGENTS.md §4.3).
- **PromoService** — `match_trigger(text)` y `execute_promo(chat_id, trigger)`; **sin LLM**, disparo por texto exacto (AGENTS.md §4.4, REQ-PRO-*).
- **CalibrationService** — `calibrate_thresholds(window_days=30)` y `detect_drift()`; solo como job programado, nunca en el pipeline (AGENTS.md §4.5).

## Reglas de dependencia

- Application Services → Learning (solo post-turno).
- Application Services → Jobs (programación).
- Jobs delegan aquí; nunca ejecutan lógica cognitiva directa.

## Implementación real (2026-08)

`application/` tiene 47 archivos. Familias reales:

- **Turno:** `turn_coordinator.py` (ciclo de vida del turno, guard de concurrencia), `turn_orchestrator.py` (wiring del caso de uso VIP, supervisado + autónomo).
- **Admin/superficie:** `admin_service.py` (cola de aprobación, sin tipos aiogram), `admin_trace_service.py`, `approval_ui.py`, `persona_admin_service.py`, `persona_catalog_provider.py` (caché en proceso).
- **Memoria (F5):** `memory_extraction_service.py` (post-turno), `memory_backfill_service.py` + `memory_backfill_queue.py` (cola durable), `memory_approval_service.py` (aprobación de sensibles).
- **Evolución de agente (shadow):** `trust_budget_service.py` (Fase 5 shadow), `emotional_signal_detector.py` (heurística v1, shadow-only), `mood_engine.py` (3 ejes, shadow), `turn_classifier.py` (Fase 2 shadow), `profile_synthesis_service.py` + `profile_synthesis_trigger_service.py` + `strong_signal_heuristics.py` (Fase 1 shadow).
- **Proactividad (F3):** `recontact_service.py` (sin LLM/Analista/Planner), `promo_service.py` (trigger exacto, sin LLM), `autonomous_mode_service.py` (gate L2 + notify cerca de umbral), `gray_zone_service.py`.
- **Calibración:** `calibration_service.py` + `calibration_math.py` (math pura, sin I/O), `metrics_service.py`.
- **Recuperación:** `recovery.py`, `recovery_startup.py` (nunca auto-envía ni auto-aprueba), `cognitive_recovery.py`, `missed_message_recovery.py`.
- **Otros:** `sandbox.py` + `sandbox_knowledge.py`, `staging_service.py`, `ports.py` (I/O ports sin aiogram), `draft_variants.py`, `owner_marks.py`, `escalation_labels.py`, `mexico_tz.py`.

^[src/diana/application/*, AGENTS.md §2.1]

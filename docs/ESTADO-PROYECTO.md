# Estado del proyecto — Diana Business Bot (DianaV2)

**Fecha:** 2026-08-05
**Rama:** main · **Head:** b196477 (pusheado)
**Bot en producción:** corriendo (PID 52278, tmux prod:3) — arranque limpio, polling activo.
**Base de datos:** migraciones al día (head `023_backfill_queue`).

---

## 1. Qué está implementado y activo

### Fase 4 — Atención al cliente general ✅ (activa)
- `FEATURE_GENERAL_MODE_ENABLED=true` en `.env`.
- Ciclo de vida por chat: trigger "Quiero más información 🔥" → promo automática sin LLM → chat habilitado por **30 días lineales** (el re-trigger no extiende).
- **El pago cierra el ciclo** (aviso a la dueña + el chat sale del proceso; la entrega es manual de la dueña).
- Límite diario 20 mensajes/chat (CDMX), fail-open si falla la base.
- Atención supervisada (los borradores pasan por aprobación de la dueña).
- Vocabulario comercial exento de la escalación en el canal de atención (`pago`/`transferencia` no cortan el flujo; `reclamación` sí escala).

### Fase 5 — Perfil de memoria por VIP 🔄 (Pools 1 y 2 hechos; 3 y 4 pendientes)
- **Pool 1 — Backfill (COMPLETO)**: migración `022` (status + source_turn_id), escritor idempotente `replace_vip_profile`, `MemoryBackfillService` (historial → LLM → ficha por secciones + fila `perfil`), paginación (200 msgs / 12K chars), filtro de visibilidad (los hechos `pending_owner`/`discarded` NUNCA llegan al contexto del bot), SEC-INJ-02 + heurística de términos sensibles (fail-closed), preserva aprobaciones al regenerar, binding chat↔VIP fail-closed.
- **Pool 2 — Disparo + cola (COMPLETO)**: migración `023` (tabla `backfill_queue`), cola persistente con pop atómico (una extracción a la vez), **timer de 1 hora entre cada extracción** (entre VIPs y entre tramos del mismo VIP — protege la cuenta de Telegram), botón **"🔄 Generar perfil"** en la ficha del panel (sin comandos nuevos), auto-encolado al registrar VIP, dedup semántico 0.85, reintentos con espera (sin gasto de LLM a lo loco), PII fuera de los logs.
- **Pools 3 y 4 — PENDIENTES** (ver §3).

### Otros
- Flag `FEATURE_MEMORY_ENABLED=true` (gate del wiring de memoria).
- Migraciones: 001-023 aplicadas. Persona sin reglas de voseo; español neutro.

---

## 2. Estado de operación (verificado 2026-08-05 19:53)

- Bot corriendo con el código de los Pools 1-2.
- Al arrancar se encolaron **8 VIPs con historial** para perfilado; **el primero ya tiene perfil generado**; los demás se procesan de a uno por hora (cola activa, sin intervención).
- Sin errores ni tracebacks en el arranque.
- Verificación de suites: **2016 unit + 89 e2e (Docker) verdes**, purity gates 3/3.

---

## 3. Qué falta (pendiente)

### Fase 5 — Pools 3 y 4
- **Pool 3 — Memoria post-turno (F5-04)**: el bot extrae hechos nuevos de cada conversación atendida (incremental), no solo del historial inicial. SPEC REQ-MEM-07. Incluye fix menor diferido: test de rechazo del CHECK `ck_backfill_queue_outcome`.
- **Pool 4 — Control de la dueña + panel + cierre (F5-05/06/10)**:
  - Aprobación/descarte por DM de los hechos sensibles (`pending_owner`) — hoy se extraen y quedan invisibles, pero no hay botones para aprobarlos.
  - Vista de la ficha de memoria en el panel (secciones, pendientes, aprobados).
  - Tests finales de anti-contaminación (VIP A no ve memoria de B; atencion no lee memoria; pendientes invisibles).

### Privacidad / F3 (decisión de producto pendiente — documentada en SPEC-FASE5 §12.7)
- El backfill envía el historial completo al LLM externo (DeepSeek) — by-design. Follow-ups opcionales: exclusión por VIP (descartada por decisión de producto: todos se perfilan), masking de PII previo al envío, retención/modelo local, acuerdo de procesamiento con el proveedor.

### Deuda técnica / mejoras menores
- `reasonix.toml` untracked (config local de tooling — decidir si va a `.gitignore`).
- Calibración de deriva: score 0.25 vs umbral 0.1 (esperado tras cambios de persona; se re-ancla en ~4 semanas).
- Recalibración del umbral de dedup 0.85 tras uso real.

### Diagnóstico verificado 2026-08-05 (perfil generado pero "no se ve nada" en el panel)
- **Extracción y escritura: correctas** (verificado en DB: el VIP 08473338-… tiene 4 hechos + fila `perfil` en `memories`, status `auto`).
- **Lectura: pendiente del Pool 4 (F5-06)** — la ficha del panel ("👤 Ver ficha") muestra la ficha manual (`profiles`), NO la memoria semántica (`memories`). La vista de memoria en el panel se implementa en el Pool 4, junto con la aprobación por DM. **No se adelanta** (decisión de la dueña: continuar gradual por pools).
- **Notificación**: "Perfil generado para {uuid}" → usar el nombre del VIP (display_name) — pendiente menor, se incluye en el Pool 4 (UX de dueña).

---

## 4. Referencias

- SPECs: `docs/SPEC-FASE4.md`, `docs/SPEC-FASE5.md` (contratos vigentes).
- Planes y trazabilidad del pipeline: `.planning/quick/20260805-f5-perfil-vip/` (PLAN.md, PLAN-POOL2.md, SUMMARYs, AUDIT-POOL2.md, REVIEWs, SECURITYs).
- Logs de agentes: `.planning/quick/gsd-*.log`.
- Repo legacy (v1, patrón de extracción): `repos/diana/services/history_backfill.py`.

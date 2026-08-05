# Estado del proyecto — Diana Business Bot (DianaV2)

**Fecha:** 2026-08-05
**Rama:** main · **Head:** b353511 (pusheado)
**Bot en producción:** corriendo (PID 88421, tmux prod:0) — arranque limpio, polling activo.
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

### Fase 5 — Perfil de memoria por VIP ✅ (COMPLETA — 4 pools)
- **Pool 1 — Backfill**: migración `022` (status + source_turn_id), escritor idempotente, `MemoryBackfillService` (historial → LLM → ficha por secciones + fila `perfil`), paginación (200 msgs / 12K chars), filtro de visibilidad (pending_owner/discarded NUNCA al contexto), SEC-INJ-02 + heurística de términos sensibles (fail-closed), preserva aprobaciones al regenerar, binding chat↔VIP fail-closed.
- **Pool 2 — Disparo + cola**: migración `023` (tabla `backfill_queue`), cola persistente con pop atómico (una extracción a la vez), **timer de 1 hora entre cada extracción** (protege la cuenta de Telegram), botón **"🔄 Generar perfil"** en la ficha del panel, auto-encolado al registrar VIP, dedup semántico 0.85, reintentos con espera, PII fuera de logs.
- **Pool 3 — Memoria post-turno**: cada conversación atendida alimenta la ficha (extracción incremental con no-repetir, dedup, sensibilidad fail-closed); best-effort (un fallo nunca afecta el turno); gate restringido a turnos entregados/escalados/fallidos.
- **Pool 4 — Control de la dueña + panel (COMPLETO)**:
  - **Aprobación por DM**: `/memoria` + botones (aprobado ✅ / descartado ❌) para hechos sensibles pendientes.
  - **La ficha del panel muestra la memoria** (sección 🧠 Memoria por secciones con estados) — resuelto el diagnóstico "perfil generado pero no se ve".
  - **Notificaciones con el nombre del VIP** (antes el UUID) + hint `/memoria`.
  - **Anti-contaminación** garantizada por tests (Telegram nunca toca la DB de memoria; pendientes/descartados invisibles al retriever; cada VIP solo ve su memoria).

### Otros
- Flag `FEATURE_MEMORY_ENABLED=true` (gate del wiring de memoria).
- Migraciones: 001-023 aplicadas. Persona sin reglas de voseo; español neutro. CHANGELOG.md creado.

---

## 2. Estado de operación (verificado 2026-08-05 22:04)

- Bot corriendo con la Fase 5 completa (PID 88421, ventana "bot" en tmux prod).
- Cola de backfill activa: los VIPs con historial se perfilan de a uno por hora (sin intervención).
- Verificación de suites: **2082 unit + 98 e2e (Docker) verdes**, purity gates 3/3.

---

## 3. Qué falta (pendiente)

### Fase 6 en adelante (nuevas fases — no definidas aún)
- El SPEC-FASE6 no existe; los siguientes pasos de producto se deciden con la dueña.

### Deuda técnica / mejoras menores (trazadas)
- `reasonix.toml` untracked (config local de tooling — decidir si va a `.gitignore`).
- Calibración de deriva: score 0.25 vs umbral 0.1 (esperado tras cambios de persona; se re-ancla en ~4 semanas).
- Recalibración del umbral de dedup 0.85 tras uso real.
- Optimizaciones menores documentadas (N+1 en lista del dueño, hint del panel top-50, lectura full-history por turno) — wontfix con justificación en los review files del Pool 4.
- Privacidad (F3, documentado en SPEC-FASE5 §12.7): follow-ups opcionales — masking de PII previo al envío al LLM, retención/modelo local, acuerdo de procesamiento con el proveedor.

---

## 4. Referencias

- SPECs: `docs/SPEC-FASE4.md`, `docs/SPEC-FASE5.md` (contratos vigentes).
- Trazabilidad del pipeline: `.planning/quick/20260805-f5-perfil-vip/` (PLAN-POOL2/3/4.md, SUMMARYs, AUDITs, REVIEWs, SECURITYs).
- Logs de agentes: `.planning/quick/gsd-*.log`.
- Repo legacy (v1, patrón de extracción): `repos/diana/services/history_backfill.py`.

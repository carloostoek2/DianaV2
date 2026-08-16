# Estado del proyecto — Diana Business Bot (DianaV2)

**Fecha:** 2026-08-16
**Rama:** main · **Head:** `a80e0d9` (docs de feedback cerrados; origin/main = local al inicio de esta auditoría).
**Bot en producción:** no re-verificado en esta fecha. El snapshot del 2026-08-11 (PID 204716, tmux prod) **no se da por vigente**.
**Base de datos (repo):** Alembic head `029_feedback_quality` (cadena 001→029).
**Base de datos (producción):** último snapshot verificado = `026` (2026-08-11). Apply de **027 / 028 / 029 en producción: SIN VERIFICAR**.

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

### Evolución de agente — pool `evo-agente` ✅ (SHADOW ACTIVO en producción — 4 ítems, 2026-08-07)
Spec `docs/SPEC-EVOLUCION-AGENTE.md` v1.2. **En modo medición/registro** (shadow): los hooks miden y guardan,
pero **no cambian ninguna decisión** — el bot sigue 100% supervisado. Migraciones 024-026 **aplicadas en producción**.

- **Fase 0 fundaciones + Detector emocional (transversal):** migración 024 (6 tablas: `vip_profile`,
  `vip_profile_history`, `vip_mood_state`, `vip_trust_budget`, `turn_category_log`, `emotional_signal_log`),
  6 repos con mapper puro + `purge_expired`, `EmotionalSignalDetector` heurístico sin LLM (umbrales fijos +
  override manual, nunca auto-calibrado), hook shadow post-turno flag-gated, `AgentDataPurgeJob`.
- **Fase 1 resíntesis de memoria:** migración 025, `strong_signal_heuristics` + `ProfileSynthesisTriggerService`
  (4 condiciones OR + dedup), `ProfileSynthesisService` (confidence gating, no sobrescribe en baja confianza) +
  `ProfileSynthesisJob` (scan+drain+release), hook de disparo + wiring + job en main, EA-05 anti-contaminación
  (el perfil jamás alimenta examples; solo `recent_trend`/mood al contexto de generación).
- **Fase 2 autonomía fática (shadow):** migración 026, `TurnClassifier` puro (4 categorías + modo "no estoy seguro").
  El carril rápido real (autoenvío) queda para cuando la fase salga de shadow: **doble puerta** trust budget +
  evaluación del Decider + filtros EA-02 (incl. chequeo de seguridad del borrador, EA-02(3)).
- **Fase 3 motor de mood (shadow):** `MoodEngine` 3 ejes (promedio móvil con retorno a base, ruido determinista),
  actualizado por turno reusando la salida del analyst (sin LLM extra); conectarlo a selección de variantes cuando
  salga de shadow.
- **Fase 5 trust budget (mecánica + ficha):** `TrustBudgetService` puro (asimetría conservadora 0.05/0.2, clamp
  [0,1], `can_autonomous` doble puerta pura **sin call-sites de envío**, `evaluation_dispersion`), repos atómicos,
  hook shadow + `handle_correct`→`record_correction` (solo si el turno era candidato autónomo), sección 🔐 Confianza
  en la ficha del VIP (EA-06). Umbrales fijos + override manual, jamás calibrados por LLM.

Flags nuevos (todos OFF por default en código; **ACTIVOS en `.env` de producción en modo medición**):
`FEATURE_EMOTIONAL_DETECTOR_ENABLED=true`, `FEATURE_PROFILE_SYNTHESIS_ENABLED=true`, `FEATURE_PHATIC_AUTONOMY=true`,
`FEATURE_MOOD_ENGINE=true`, `FEATURE_TRUST_BUDGET=true` — con `FEATURE_AUTONOMOUS_MODE=false` (nada se autoenvía).
El comentario del `.env` lo explicita: *"Turning on only measures/records"*. Verificaciones: 4 review loops a 0 open
(3 rondas c/u); suite unit 2441 passed / 2 pre-existentes (`test_sql_repo_shapes.py`, no atribuibles); e2e DB verde
con Docker. **Datos shadow reales en producción (verif. 2026-08-11):** `turn_category_log` 48, `emotional_signal_log` 29,
`vip_profile` 9 (versiones hasta v7), `vip_profile_history` 9, `vip_mood_state` 8, `vip_trust_budget` 2 (fático, score ~0.18).
**Pendiente:** cola durable `synthesis_queue`, ficha perfil EA-06 completa (historial de versiones),
`.env.example` con los flags nuevos, y la Fase 5 real (doble puerta) cuando F2 salga de shadow.

### Fase 6 — Vínculo entre bots (Lucien → Diana) para aviso de expulsión VIP ✅ (IMPLEMENTADO — flag OFF, 2026-08-15)
Spec `docs/SPEC-FASE6.md` v1.0 (REQ-LNK-01..10). Two-repo feature: cuando **Lucien** expulsa a un suscriptor
del Canal VIP (revoke manual, expiración por scheduler, o limpieza de startup — los 3 puntos de emisión cubiertos),
notifica a **Diana** vía chat de coordinación con un payload `[LINK]` one-line; Diana verifica si el expulsado es
VIP activo y, si lo es, pide a la dueña **Expulsar / Desactivar / Mantener** con 3 botones. Todo detrás de
`FEATURE_LINK_ENABLED` (default `false` en ambos bots; OFF = comportamiento idéntico).

- **Parte A (emisor, repo `lucienbot`):** `business_connections` table + handler, `LinkNotifier` + event bus
  (`EVENT_VIP_KICKED`), 3 kick hooks, config flag.
- **Parte B (receptor/decisor, DianaV2):** migración `028_link_events` + `LinkCoordinator` (dedup idempotente por
  `event_id` → verify-VIP → notificar → decidir), `notify_link` + keyboard 3 botones, `LinkCoordinatorMiddleware`
  que consume el `[LINK]` en la capa de middleware (antes de `OwnerDetectionMiddleware`, corrección a REQ-LNK-04),
  callback router `link:*` owner-gated, settings `feature_link_enabled`/`link_chat_id`/`link_disable_frozen_until`.
- **Verificado:** 4/4 ítems del pool, review loops a 0 open, `tests/unit` 2639 passed / 0 failed, purity gates 17 passed.
- **Pendiente:** **integration spike** en deploy real (Railway+EC2) — dueña conecta su cuenta de negocio a Lucien,
  expulsa un usuario de prueba, verifica que Diana reciba `[LINK]`. Es el acceptance step final para encender el flag.
  Migración real de `link_events`: **028** (el SPEC aún cita 027; 027 se usó para eventos temporales).

### Feedback de calidad — Destacar / Reprender ✅ (IMPLEMENTADO — flag OFF, 2026-08-16)
Spec `docs/SPEC-FEEDBACK.md`. Pool `feedback-calidad` cerrado (4 ítems). **No está encendido** hasta que la dueña active `FEATURE_QUALITY_FEEDBACK_ENABLED` (default `false`; ahora documentado en `.env.example`).

- En borradores **VIP** (nunca Atención): botones Destacar / Reprender.
- **Destacar:** confirma alcance (este VIP o global) y guarda el ejemplo como oro. No pasa por la cola de staging.
- **Reprender:** el texto de corrección **se entrega ya** al VIP; después se elige si esa lección queda para este VIP o para todas.
- El banco de ejemplos ya ordena primero los destacados (gold-first) y separa lecciones por VIP, aunque el flag esté apagado.
- Si falla el aviso de consulta de doctrina al VIP, el sistema **descongela** y manda el borrador a aprobación (no deja al VIP trabado).
- Migración **029** (`examples.quality`, `examples.vip_id`, `policies.vip_id`). Apply en producción: SIN VERIFICAR.

### Eventos temporales ✅ (IMPLEMENTADO — sin flag, 2026-08-12)
La dueña puede cargar un dato de contexto con fecha de inicio y fin (menú 📅 Eventos temporales). Entra al contexto como `knowledge.ephemeral` (global, no por VIP). No se mezcla con la memoria del VIP ni con el banco de ejemplos. Migración **027**. Siempre cableado.

### UX de la dueña (A1–A13) ✅ cerrado 2026-08-12
Menú unificado como superficie principal. Progreso en vivo al aprobar (visto → escribiendo → enviado), “Regenerando…” al pedir otra versión, avisos honestos si el botón ya no aplica, nombre del VIP en el borrador, tipos de archivo etiquetados, doctrina en texto libre (`dr:`). Detalle en `docs/UX.md`.

### Otros
- Flag `FEATURE_MEMORY_ENABLED=true` (gate del wiring de memoria).
- Migraciones en repo: **001–029**. En producción, verificado hasta **026** (2026-08-11). **027 ephemeral + 028 link + 029 quality: apply en producción SIN VERIFICAR.**
- Persona sin reglas de voseo; español neutro. CHANGELOG.md vigente.
- Auditoría de documentación 2026-08-16: wiki + estado alineados al código post-11-ago. Informes en `.planning/quick/docs-audit-2026-08-16/`.

---

## 2. Estado de operación

### Snapshot verificado 2026-08-11 (no re-medido el 16)
- Bot con Fase 5 + evo-agente en modo medición (PID 204716 en ese momento).
- Memoria: 81 filas en `memories` (52 auto, 18 discarded, 11 approved); 10 backfills.
- Suite de entonces: 2441 unit + e2e verdes. El pool feedback posterior reportó suites más grandes (p. ej. 2639 en el cierre de Fase 6); **no se re-corrió la suite en esta auditoría de docs**.

### Lo que cambió en el repo desde ese snapshot (verificado en código, 2026-08-16)
- Fase 6, eventos temporales, Destacar/Reprender y el arreglo de menú **están en `main`**.
- El bot **sigue 100 % supervisado** si `FEATURE_AUTONOMOUS_MODE=false` (la doble puerta de envío autónomo no está cableada).
- Destacar/Reprender y el aviso Lucien **no actúan** hasta encender sus flags.
- Eventos temporales **sí actúan** en cuanto exista la tabla 027 (no tienen interruptor).

---

## 3. Qué falta (pendiente)

### Fase 6 / feedback / datos
- Fase 6 **implementada y cerrada en código** — queda el integration spike de deploy para encender `FEATURE_LINK_ENABLED`.
- Destacar/Reprender **implementado y cerrado en código** — queda decidir cuándo encender `FEATURE_QUALITY_FEEDBACK_ENABLED` (y aplicar 029 en producción).
- Aplicar en producción, en orden: **027** (eventos temporales, siempre activos al existir la tabla) → **028** (link) → **029** (calidad). Hoy: SIN VERIFICAR.
- Las siguientes fases se deciden con la dueña.

### Evolución de agente — pendiente del pool `evo-agente` (ver SPEC-EVOLUCION-AGENTE.md v1.2)
- **Fase 5 real (cablear la doble puerta):** `decision.action=="send" AND can_autonomous(...)`
  en `_prepare_autonomous_send`, interpretar/resetear la semántica shadow del incremento, filtro EA-02(3) (chequeo de
  seguridad del borrador). Requiere que la medición shadow acumule confianza por categoría suficiente + `recent_trend`
  confiable; hoy los flags están ON en modo medición, la puerta no está cableada a ningún envío.
- **Cola durable `synthesis_queue`** para la resíntesis de memoria (hoy guard en memoria).
- **Ficha perfil EA-06 completa** (historial de versiones de `vip_profile_history`).
- ~~**`.env.example`** flags evo-agente~~ — ✅ ya estaban. El 2026-08-16 se añadió `FEATURE_QUALITY_FEEDBACK_ENABLED`.
- ~~**Fixture de `test_sql_repo_shapes.py`**~~ — ✅ resuelto: el commit `4d30d1f` (repair CI unit suite) ya lo arregló
  (10/10 pasando).
- **Fase 4 (iniciativa contextual)** — diferida por decisión del usuario; queda especificada en el SPEC v1.2.

### Deuda técnica / mejoras menores (trazadas)
- `reasonix.toml` untracked (config local de tooling — decidir si va a `.gitignore`).
- Calibración de deriva: score 0.25 vs umbral 0.1 (esperado tras cambios de persona; se re-ancla en ~4 semanas).
- Recalibración del umbral de dedup 0.85 tras uso real.
- Optimizaciones menores documentadas (N+1 en lista del dueño, hint del panel top-50, lectura full-history por turno) — wontfix con justificación en los review files del Pool 4.
- Privacidad (F3, documentado en SPEC-FASE5 §12.7): follow-ups opcionales — masking de PII previo al envío al LLM, retención/modelo local, acuerdo de procesamiento con el proveedor.

---

## 4. Referencias

- SPECs: `docs/SPEC-FASE4.md`, `docs/SPEC-FASE5.md`, `docs/SPEC-FASE6.md`, `docs/SPEC-FEEDBACK.md`, `docs/SPEC-EVOLUCION-AGENTE.md` (v1.2, pool evo-agente F0-F5 shadow).
- Auditoría docs 2026-08-16: `.planning/quick/docs-audit-2026-08-16/`.
- Trazabilidad del pipeline: `.planning/quick/20260805-f5-perfil-vip/` (PLAN-POOL2/3/4.md, SUMMARYs, AUDITs, REVIEWs, SECURITYs).
- Logs de agentes: `.planning/quick/gsd-*.log`.
- Repo legacy (v1, patrón de extracción): `repos/diana/services/history_backfill.py`.

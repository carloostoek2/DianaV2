# Estado del proyecto — Diana Business Bot (DianaV2)

**Fecha:** 2026-08-22
**Rama:** main · **Head:** `7cf8ce7` (fix(application): gate per-VIP state writes under sandbox).
**Bot en producción:** Fase 6 (link Lucien→Diana) desplegada y verificada E2E — bot-to-bot DM, aceptación real pasada. Flags `FEATURE_LINK_ENABLED` y `FEATURE_QUALITY_FEEDBACK_ENABLED` activos en `.env`. <!-- VERIFY: estado del deploy real (Railway+EC2) y aceptación E2E no verificables desde el repo -->
**Base de datos (repo):** Alembic head `029_feedback_quality` (cadena 001→029).
**Base de datos (producción):** **VERIFICADO 2026-08-22: 001→029 aplicadas.** Las migraciones 027 (ephemeral_events), 028 (link_events) y 029 (feedback quality) ya estaban aplicadas en la base real de Supabase; se confirmó además la presencia de datos reales (`link_events` 14 filas, `examples.quality='gold'` 2 filas, `ephemeral_events` 1 fila). El ítem operativo pendiente quedó cerrado.

---

## 1. Qué está implementado y activo

### Estado del sistema (resumen)

| Área | Estado |
| --- | --- |
| Conversación VIP supervisada | Implementado |
| Atención general (Fase 4) | Implementado |
| Memoria VIP (Fase 5) | Implementado |
| Perfiles evolutivos | Implementado — shadow |
| Detección emocional | Implementado — shadow |
| Mood engine | Implementado — shadow |
| Trust budget | Implementado — shadow |
| Sandbox | Implementado |
| Staging / revisión humana | Implementado |
| Métricas y trazabilidad | Implementado |
| Feedback de calidad | Implementado — activo |
| Eventos temporales | Implementado |
| Integración Lucien → Diana (Fase 6) | Implementado — activo |
| Privacidad: masking de PII al LLM | Implementado — activo |
| Autonomía conversacional | En evolución (medición shadow) |
| Autoenvío autónomo | No habilitado |

> El estado del código no implica que todas las funcionalidades estén activadas en producción; las capacidades experimentales y de alto impacto están protegidas mediante feature flags.

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
  La doble puerta de autoenvío (trust budget + evaluación del Decider + filtros EA-02, incl. chequeo de seguridad
  del borrador EA-02(3)) está **cableada tras `FEATURE_AUTONOMOUS_MODE` pero deshabilitada** por el kill-switch L1:
  en shadow solo mide, no envía.
- **Fase 3 motor de mood (shadow):** `MoodEngine` 3 ejes (promedio móvil con retorno a base, ruido determinista),
  actualizado por turno reusando la salida del analyst (sin LLM extra). No está conectado a la selección de
  variantes — solo medición.
- **Fase 5 trust budget (mecánica + ficha):** `TrustBudgetService` puro (asimetría conservadora 0.05/0.2, clamp
  [0,1], `can_autonomous` doble puerta pura, `evaluation_dispersion`), repos atómicos, hook shadow +
  `handle_correct`→`record_correction` (solo si el turno era candidato autónomo), sección 🔐 Confianza en la ficha
  del VIP (EA-06). Umbrales fijos + override manual, jamás calibrados por LLM. La doble puerta no gobierna ningún
  envío real porque `FEATURE_AUTONOMOUS_MODE=false`, aunque el pipeline de envío autónomo sí está cableado tras el
  flag (`turn_orchestrator.py` ~304/2549, `recontact_service.py` ~209).

Flags nuevos (todos OFF por default en código; **ACTIVOS en `.env` de producción en modo medición**):
`FEATURE_EMOTIONAL_DETECTOR_ENABLED=true`, `FEATURE_PROFILE_SYNTHESIS_ENABLED=true`, `FEATURE_PHATIC_AUTONOMY=true`,
`FEATURE_MOOD_ENGINE=true`, `FEATURE_TRUST_BUDGET=true` — con `FEATURE_AUTONOMOUS_MODE=false` (nada se autoenvía).
El comentario del `.env` lo explicita: *"Turning on only measures/records"*. Verificaciones: 4 review loops a 0 open
(3 rondas c/u); suite unit 2441 passed / 2 pre-existentes (`test_sql_repo_shapes.py`, no atribuibles); e2e DB verde
con Docker. **Datos shadow reales en producción (verif. 2026-08-11):** `turn_category_log` 48, `emotional_signal_log` 29,
`vip_profile` 9 (versiones hasta v7), `vip_profile_history` 9, `vip_mood_state` 8, `vip_trust_budget` 2 (fático, score ~0.18).
**Pendiente:** cola durable `synthesis_queue` y ficha perfil EA-06 completa (historial de versiones) — ver §3.

### Fase 6 — Vínculo entre bots (Lucien → Diana) para aviso de expulsión VIP ✅ (IMPLEMENTADO Y ACTIVO — 2026-08-21)
Spec `docs/SPEC-FASE6.md` v1.0 (REQ-LNK-01..10). Two-repo feature: cuando **Lucien** expulsa a un suscriptor
del Canal VIP (revoke manual, expiración por scheduler, o limpieza de startup — los 3 puntos de emisión cubiertos),
notifica a **Diana** vía chat de coordinación con un payload `[LINK]` one-line; Diana verifica si el expulsado es
VIP activo y, si lo es, pide a la dueña **Expulsar / Desactivar / Mantener** con 3 botones. Todo detrás de
`FEATURE_LINK_ENABLED` (default `false` en código; **activo en `.env`**: `FEATURE_LINK_ENABLED=true`).

- **Parte A (emisor, repo `lucienbot`):** `business_connections` table + handler, `LinkNotifier` + event bus
  (`EVENT_VIP_KICKED`), 3 kick hooks, config flag.
- **Parte B (receptor/decisor, DianaV2):** migración `028_link_events` + `LinkCoordinator` (dedup idempotente por
  `event_id` → verify-VIP → notificar → decidir), `notify_link` + keyboard 3 botones, `LinkCoordinatorMiddleware`
  que consume el `[LINK]` en la capa de middleware (antes de `OwnerDetectionMiddleware`, corrección a REQ-LNK-04),
  callback router `link:*` owner-gated, settings `feature_link_enabled`/`link_chat_id`/`link_disable_frozen_until`.
- **Verificado:** 4/4 ítems del pool, review loops a 0 open, `tests/unit` 2639 passed / 0 failed, purity gates 17 passed.
- **Integration spike completado:** Fase 6 desplegada y verificada E2E (bot-to-bot DM, aceptación real pasada);
  el flag quedó encendido. Migración real de `link_events`: **028** (el SPEC aún cita 027; 027 se usó para eventos temporales).

### Feedback de calidad — Destacar / Reprender ✅ (IMPLEMENTADO Y ACTIVO — 2026-08-21)
Spec `docs/SPEC-FEEDBACK.md`. Pool `feedback-calidad` cerrado (4 ítems). **Activo**: `FEATURE_QUALITY_FEEDBACK_ENABLED=true` en `.env` (default `false` en código, overridable por env).

- En borradores **VIP** (nunca Atención): botones Destacar / Reprender.
- **Destacar:** confirma alcance (este VIP o global) y guarda el ejemplo como oro. No pasa por la cola de staging.
- **Reprender:** el texto de corrección **se entrega ya** al VIP; después se elige si esa lección queda para este VIP o para todas.
- El banco de ejemplos ya ordena primero los destacados (gold-first) y separa lecciones por VIP, aunque el flag esté apagado.
- Si falla el aviso de consulta de doctrina al VIP, el sistema **descongela** y manda el borrador a aprobación (no deja al VIP trabado).
- Migración **029** (`examples.quality`, `examples.vip_id`, `policies.vip_id`). Apply en producción: SIN VERIFICAR (pendiente operativo).

### Eventos temporales ✅ (IMPLEMENTADO — sin flag, 2026-08-12)
La dueña puede cargar un dato de contexto con fecha de inicio y fin (menú 📅 Eventos temporales). Entra al contexto como `knowledge.ephemeral` (global, no por VIP). No se mezcla con la memoria del VIP ni con el banco de ejemplos. Migración **027**. Siempre cableado.

### Privacidad — masking de PII al LLM ✅ (IMPLEMENTADO — ACTIVO, 2026-08-22)
Cierre de la deuda "Masking de PII previo al envío al LLM (SPEC-FASE5 §12.7, F3)".

- **Dónde:** en el borde de salida hacia el proveedor (`DeepSeekProvider.generate` / `generate_structured`), un único punto que cubre todas las llamadas: analista, generador, evaluador, memoria, backfill y síntesis de perfiles.
- **Qué se enmascara:** correos, teléfonos (formatos MX e internacionales), tarjetas (validadas con checksum Luhn), @usuarios y enlaces → reemplazados por marcadores `[correo]`, `[telefono]`, `[tarjeta]`, `[usuario]`, `[enlace]` a prueba de colisiones.
- **Transparencia total:** si el modelo repite un marcador en la respuesta, se restaura al valor original antes de llegar al VIP o persistirse (el texto que ve el VIP y lo que queda en `pipeline_traces` no cambia). Nombres propios **no** se enmascaran (personalización los necesita; el acuerdo legal con el proveedor cubre esa parte).
- **Flag:** `FEATURE_PII_MASKING_ENABLED` (default `true` en código — única excepción a la convención de flags en false, porque es privacidad y es transparente por diseño). Interruptor para depuración.
- **Acuerdo con el proveedor:** guía de negociación lista en `docs/ACUERDO-PROVEEDOR-LLM.md` (qué pedir a DeepSeek: ubicación, retención, entrenamiento, seguridad, subprocesadores, DPA).
- Verificado: suite unit **2796 passed / 0 failed** (20 tests nuevos de masking).

### Fila 2 — Control de la dueña ✅ (COMPLETA, 2026-08-22)
Tres mejoras de control cerradas:

- **GAP-11 — Alcance al crear políticas:** al resolver una consulta de zona gris (responder con texto o usar borrador), la dueña elige **"🔒 Solo este VIP"** o **"🌍 A todos"** antes de guardar la regla. El alcance (`vip_id`/`scope`) viaja en el candidato de staging para que la promoción respete el alcance. Consultas de Atención (sin VIP) resuelven global directo, sin cambio.
- **EA-06 — Historial de versiones del perfil:** la ficha del VIP muestra la sección **📚 Historial de versiones** (últimas 5, con fecha y resumen del cambio), alimentada de `vip_profile_history` (sin migración). Flag OFF → ficha byte-idéntica.
- **ADM-03 — Cambio de modelo de IA en caliente:** `HotSwapLLMProvider` relee la config `system_config["llm"]` (modelo/servidor/llave) con TTL de 30s y reconstruye el proveedor sin reiniciar. Superficie: **⚙️ Configuración → 🤖 Modelo de IA** (ver modelo activo, cambiar con wizard de texto, restablecer). Nuevo setting `LLM_MODEL` (default `deepseek-v4-flash`). Sin overrides → comportamiento byte-idéntico al proveedor base.

Suite: **2841 unit tests passing**.

### Consulta del modo sombra en el menú de la dueña ✅ (IMPLEMENTADO, 2026-08-22)
Sección **"🤖 Modo sombra"** en el menú de la dueña (consulta bajo demanda, sin notificaciones):

- **📊 Resumen y umbrales:** turnos medidos en los últimos 7 días con tendencia diaria, totales ("habría enviado sola", correcciones de la dueña), umbrales actuales (confianza 0.90, clasificador 0.70) y el mensaje que habría enviado (`"Holis 😁"`).
- **👥 Confianza por VIP:** score por (VIP, categoría) comparado con el umbral (✅ cumple / ⏳ en camino), contadores de autónomos y correcciones.
- **💬 Borradores y decisiones:** simulación con **autonomía total**: cada turno real se re-decide con el **Decisor real** (misma matriz, interruptor de autonomía ENCENDIDO) sobre la evaluación y comprensión guardadas del turno. Muestra: decisión real vs. veredicto con autonomía (✅ habría enviado / ❌ umbrales no alcanzados con detalle por dimensión seguridad/doctrina/naturalidad vs mínimos / ❌ escalado por riesgo o VIP molesta / ❌ doctrina pendiente), la compuerta de confianza por VIP (cómo se va "abriendo" la autonomía), el borrador real generado (el mismo que la dueña aprueba) y la nota del interruptor maestro apagado. Sin migraciones: todo se reconstruye de `pipeline_traces` (evaluation/comprehension/decision) + `turn_category_log`.
- **Nada cambia en el comportamiento:** la sección es solo lectura (`AdminShadowService`); los flags de autonomía siguen apagados.
- **Sin migraciones:** el borrador ya se persistía (`pipeline_traces.generated_text`); la vista solo lo une con `turn_category_log`.

Verificado contra la base real: 69 turnos medidos en 7 días, 14 "habría enviado", 6 VIPs con confianza 0.15–0.45 (ninguno sobre el umbral).

### UX de la dueña (A1–A13) ✅ cerrado 2026-08-12
Menú unificado como superficie principal. Progreso en vivo al aprobar (visto → escribiendo → enviado), “Regenerando…” al pedir otra versión, avisos honestos si el botón ya no aplica, nombre del VIP en el borrador, tipos de archivo etiquetados, doctrina en texto libre (`dr:`). Detalle en `docs/UX.md`.

### Otros
- Flag `FEATURE_MEMORY_ENABLED=true` (gate del wiring de memoria).
- Migraciones en repo: **001–029**. En producción: **verificadas al head 029** (2026-08-22).
- Persona sin reglas de voseo; español neutro. CHANGELOG.md vigente.
- Auditoría de documentación 2026-08-16: wiki + estado alineados al código post-11-ago. Informes en `.planning/quick/docs-audit-2026-08-16/`.

---

## 2. Estado de operación

### Snapshot verificado 2026-08-11 (no re-medido el 21)
- Bot con Fase 5 + evo-agente en modo medición (PID 204716 en ese momento).
- Memoria: 81 filas en `memories` (52 auto, 18 discarded, 11 approved); 10 backfills.
- Suite de entonces: 2441 unit + e2e verdes. El pool feedback posterior reportó suites más grandes (p. ej. 2639 en el cierre de Fase 6); **no se re-corrió la suite completa en esta actualización**.

### Lo que cambió en el repo desde ese snapshot (verificado en código, 2026-08-21)
- Fase 6, eventos temporales, Destacar/Reprender y el arreglo de menú **están en `main`**; Fase 6 desplegada.
- El bot **sigue 100 % supervisado**: `FEATURE_AUTONOMOUS_MODE=false` mantiene apagada la ruta de envío autónomo. La doble puerta está cableada tras el flag, pero el kill-switch L1 la desactiva (nada se autoenvía).
- Destacar/Reprender y el aviso Lucien **están activos** en `.env` (`FEATURE_QUALITY_FEEDBACK_ENABLED=true`, `FEATURE_LINK_ENABLED=true`).
- Eventos temporales **sí actúan** en cuanto exista la tabla 027 (no tienen interruptor).

---

## 3. Qué falta (pendiente real)

> Pendientes de implementación y operación al 2026-08-21. Ningún ítem está "en curso de implementación"; se listan porque aún no existen o están diferidos. Referencia de IDs: `docs/INFORME_AUDITORIA.md` y `REQUERIMIENTOS.md`.

### Requerimientos no implementados (auditoría 2026-07)
- **AUTH-03 — Tope configurable de VIPs:** no implementado. No existe límite/capacidad de VIPs en `settings.py` (solo `vip_history_seed_limit`, que limita seed de historial, no cantidad de VIPs).
- **AUTH-07 — Modo observación silenciosa de chats no-VIP:** no implementado. Solo existe training mode que responde; no hay rama de observación pasiva/silencio.
- ~~**GAP-11 — Generalización explícita al crear políticas**~~ → **CERRADO 2026-08-22** (alcance preguntado a la dueña; ver Fila 2).
- **REE-02 / COG-15 — Recontacto con pipeline reducido:** no implementado. `recontact_service.py` usa plantillas fijas (`{nombre}`/`{producto}`), sin personalización por pipeline ni pipeline reducido.
- **MODE-09 — Feedback post-send autónomo dedicado:** no implementado. Solo existe la corrección de turno (Destacar/Reprender); no hay calificador post-envío.
- ~~**ADM-03 — Cambio de LLM en caliente**~~ → **CERRADO 2026-08-22** (`HotSwapLLMProvider` + superficie Configuración → Modelo de IA; ver Fila 2).

### Evolución de agente — pendiente real
- **Autoenvío (doble puerta): deshabilitado.** `FEATURE_AUTONOMOUS_MODE=false`; la ruta de envío autónomo está cableada tras el flag (`turn_orchestrator.py` ~304/2549, `recontact_service.py` ~209) pero apagada. En shadow solo se acumula medición (trust budget por VIP/categoría, `recent_trend`); no hay envío autónomo.
- **Cola durable `synthesis_queue` para síntesis de perfiles:** no implementada (hoy guard en memoria).
- ~~**Ficha de perfil EA-06 con historial de versiones**~~ → **CERRADO 2026-08-22** (sección 📚 en la ficha; ver Fila 2).

### Operativo y despliegue
- ~~Migraciones 027-029 en producción: pendiente~~ → **CERRADO 2026-08-22**: verificadas aplicadas en la base real (ver cabecera).
- **Acuerdo con el proveedor de IA (DeepSeek):** pendiente de gestión de la dueña — guía en `docs/ACUERDO-PROVEEDOR-LLM.md`. No bloquea al bot (el masking ya está activo).
- **Fase 4 de evolución de agente (iniciativa contextual):** especificada pero diferida por decisión de producto (no confundir con la Fase 4 de Atención general, implementada).

### Deuda técnica / mejoras menores (trazadas)
- Ampliar el masking a direcciones/CURP/RFC y nombres (versión 2; hoy cubre correos, teléfonos, tarjetas, @usuarios y enlaces).
- Retención/modelo local y acuerdo de procesamiento con el proveedor (privacidad, F3 — la parte legal sigue pendiente de la dueña).
- Recalibración del umbral de dedup 0.85 tras uso real.
- Calibración de deriva: score 0.25 vs umbral 0.1 (esperado tras cambios de persona; se re-ancla en ~4 semanas).
- `reasonix.toml` untracked (config local de tooling — decidir si va a `.gitignore`).

---

## 4. Referencias

- SPECs: `docs/SPEC-FASE4.md`, `docs/SPEC-FASE5.md`, `docs/SPEC-FASE6.md`, `docs/SPEC-FEEDBACK.md`, `docs/SPEC-EVOLUCION-AGENTE.md` (v1.2, pool evo-agente F0-F5 shadow).
- Privacidad: `docs/ACUERDO-PROVEEDOR-LLM.md` (guía del acuerdo con el proveedor de IA) y `src/diana/llm/pii_masker.py` (masking, tests en `tests/unit/llm/test_pii_masker.py`).
- Auditoría docs 2026-08-16: `.planning/quick/docs-audit-2026-08-16/`.
- Trazabilidad del pipeline: `.planning/quick/20260805-f5-perfil-vip/` (PLAN-POOL2/3/4.md, SUMMARYs, AUDITs, REVIEWs, SECURITYs).
- Logs de agentes: `.planning/quick/gsd-*.log`.
- Repo legacy (v1, patrón de extracción): `repos/diana/services/history_backfill.py`.

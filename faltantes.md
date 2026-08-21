# Faltantes del sistema — catálogo consolidado

> Único punto de consulta de lo que **no está implementado o no está activo** en DianaV2 (2026-08-21).
> Lo que no aparece aquí está implementado y activo. Consolidado desde `docs/ESTADO-PROYECTO.md`,
> `docs/INFORME_AUDITORIA.md`, `docs/SPEC-FASE5.md`, `docs/SPEC-EVOLUCION-AGENTE.md`, `docs/SPEC-FEEDBACK.md`
> y `docs/ANEXO-H.md`. Sin lenguaje de implementación futura: cada ítem reporta su estado actual
> (no implementado / parcial / diferido por decisión de producto / deshabilitado / pendiente de verificación).

---

## 1. Auditoría de requerimientos

Ítems detectados en la auditoría de alineamiento código ↔ REQUERIMIENTOS.md (2026-07, re-verificada 2026-08-21). Fuente principal: `docs/INFORME_AUDITORIA.md`; también `docs/ESTADO-PROYECTO.md` §3.

| ID | Ítem | Estado | Fuente |
|---|---|---|---|
| AUTH-03 | Tope configurable de VIPs: no existe límite/capacidad en `settings.py` (solo `vip_history_seed_limit`, que limita seed de historial, no la cantidad de VIPs) | No implementado | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md` |
| AUTH-07 | Modo observación silenciosa de chats no-VIP (escuchar sin responder, solo para aprender): solo existe training mode que responde; no hay rama de observación pasiva | No implementado (= brecha v1→v2 #12, ver §3) | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md` |
| GAP-11 | Generalización explícita al crear políticas: el campo `generalization` existe y se persiste (`gray_zone_service.py`, `policy_distiller.py`), pero `doctrine.py` (~265-273) pasa `generalization=rule=text` sin preguntar el alcance a la dueña | Parcial | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md` |
| GAP-08 | Comando dedicado para listar/desactivar políticas de doctrina activas desde admin: no existe (el panel "Políticas de conducta" edita el catálogo de persona versionado, almacén distinto de la tabla `policies`) | No implementado | `docs/INFORME_AUDITORIA.md`, `docs/SPEC-FEEDBACK.md` |
| REE-02 / COG-15 | Recontacto con pipeline reducido: `recontact_service.py` usa plantillas fijas (`{nombre}`/`{producto}`), sin personalización por pipeline ni pipeline reducido | No implementado | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md` |
| MODE-09 | Feedback post-send autónomo dedicado: solo existe la corrección de turno (Destacar/Reprender); no hay calificador post-envío | No implementado | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md` |
| ADM-03 | Cambio de LLM en caliente: `DeepSeekProvider` fija `base_url` en construcción desde `settings.llm_base_url`; no hay override vía `system_config` (los overrides existentes son solo para `phatic_classifier`, `profile_synthesis`, `trust_budget`) | No implementado | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md`, `docs/MVP_COMPONENT_DESIGN.md` |
| EVAL-04 | Visualización de calibración por dimensión: el resumen semanal muestra tasa global y drift, no tabla por dimensión | No implementado | `docs/INFORME_AUDITORIA.md` |

---

## 2. Autonomía y evolución de agente

Fuente principal: `docs/SPEC-EVOLUCION-AGENTE.md` v1.2 y `docs/ESTADO-PROYECTO.md` §3.

- **Autoenvío autónomo (doble puerta) — deshabilitado.** `FEATURE_AUTONOMOUS_MODE=false` en `.env` (default en `settings.py`). La ruta de envío autónomo está cableada tras el flag (`turn_orchestrator.py` ~304 y ~2549, `recontact_service.py` ~209) pero el kill-switch L1 la desactiva. En shadow solo se acumula medición (trust budget por VIP/categoría, `recent_trend`); nada se autoenvía. Fuente: `docs/ESTADO-PROYECTO.md`, `docs/SPEC-FASE3.md`, `docs/SPEC-EVOLUCION-AGENTE.md`.
- **Autonomía fática real (carril rápido F2) más allá del saludo puro — no implementada.** El clasificador y el carril rápido están en shadow: clasifican y registran, no autoenvían. El saludo puro se resuelve con plantilla (`reason=plantilla_saludo`, sin Planner/Generator/Evaluator/Decider), no con envío autónomo personalizado. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` §Fase 2, `docs/ANEXO-H.md`.
- **Escalación forzada del detector emocional — no implementada.** La escalación del detector es shadow-only: se loguea y compara `pipeline_would_have_escalated`; no fuerza al Decider. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` (componente transversal).
- **Cola durable `synthesis_queue` para síntesis de perfiles — no implementada.** Hoy el guard es en memoria (`profile_synthesis_job.py`: `drain_pending`/`release` con `_in_flight`); no hay cola persistente. Fuente: `docs/ESTADO-PROYECTO.md`.
- **Ficha de perfil EA-06 con historial de versiones — no implementada.** La ficha muestra memoria y la sección de confianza, pero no el historial de versiones de `vip_profile_history`. Fuente: `docs/ESTADO-PROYECTO.md`, `docs/SPEC-EVOLUCION-AGENTE.md` (EA-06).
- **Fase 4 de evolución de agente (iniciativa contextual) — diferida por decisión de producto.** Especificada en el spec; no confundir con la Fase 4 de Atención general, que sí está implementada. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` §Fase 4, `docs/ESTADO-PROYECTO.md`.

---

## 3. Brechas v1→v2 pendientes

Del análisis de brechas v1→v2 (los ítems resueltos se eliminaron de este catálogo). Fuente principal: este archivo antes de la consolidación y `docs/CHECKLIST_ANILLO_OPERATIVO.md`.

| Brecha | Estado | Fuente |
|---|---|---|
| #8 — Contexto temporal / rutina semanal: `ScheduleRetriever` listo (matching día/hora en America/Mexico_City, `knowledge.schedule`), pero la inyección es condicional — el Planner decide `needs_schedule`, no se inyecta en every prompt como en v1 | Parcial | brechas v1→v2, `docs/CHECKLIST_ANILLO_OPERATIVO.md` (F2) |
| #12 — Observación de mensajes no autorizados con persistencia: no existe el modo; los no-VIP van a training mode, promo o se descartan con log `auth_drop_not_allowed` | No implementado (= AUTH-07, ver §1) | brechas v1→v2 |

---

## 4. Feedback de calidad

Fuente principal: `docs/SPEC-FEEDBACK.md`.

- **UI para editar manualmente el `trigger`/`rule` autogenerado de una política creada por reprimenda — no implementada.** Las políticas de reprimenda se guardan en la tabla `policies` del DB vía `promote_to_policy`; el `trigger` autogenerado queda tal como se creó, sin flujo de edición posterior. El panel "Políticas de conducta" (`persona_admin.py`) edita un almacén distinto (persona versionada en JSON).
- **Marcar dorado/reprimenda de forma retroactiva sobre historial ya entregado (vía `/traza`) — no implementado** (descartado en la sesión de diseño; fuera de alcance explícito).
- **Enganchar la reprimenda al `vip_trust_budget` del Evo-Agente (bajar confianza a la categoría del turno) — no implementado** (mencionado como extensión; fuera de alcance explícito).

---

## 5. Privacidad y deuda técnica

### Privacidad del backfill (nota de diseño, fix round F3 — hallazgo de security-auditor)

Durante el backfill, el historial completo del chat del VIP se envía al proveedor LLM externo (DeepSeek) para la extracción (comportamiento by-design, REQ-MEM-04). Controles actuales: ventana de 200 mensajes + tope de 12K caracteres por ventana + líneas truncadas a 400 caracteres, y ninguna escritura fuera de `memories`. Pendientes **no implementados** (`docs/SPEC-FASE5.md` §12.7):

- (a) flag de exclusión por VIP (opt-out del backfill) — no implementado.
- (b) evaluar redacción/masking de PII previo al envío cuando no sea necesaria para la extracción — no implementado.
- (c) documentar retención y evaluar modelo local/on-prem para extracción sensible — no implementado.
- (d) confirmar acuerdo de procesamiento de datos con el proveedor — no implementado.

### Deuda técnica

- **Recalibración del umbral de dedup (0.85)** tras uso real — pendiente. Fuente: `docs/ESTADO-PROYECTO.md`, `docs/SPEC-FASE5.md`.
- **Calibración de deriva:** score 0.25 vs umbral 0.1 (esperado tras cambios de persona); re-anclar baseline en ~4 semanas — pendiente operativo. Fuente: `docs/ESTADO-PROYECTO.md`.
- **Política de purga/retención para tablas del Evo-Agente** (`vip_profile_history`, `turn_category_log`, `emotional_signal_log`) — no definida; crecen sin límite. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` §Fase 0.
- **Calibración automática semanal — deshabilitada.** El job existe pero está gateado por `FEATURE_CALIBRATION_ENABLED=false` (default en `settings.py`, `false` en `.env`). Fuente: `docs/MVP_COMPONENT_DESIGN.md`, código (`main.py` job gate).
- **`reasonix.toml` untracked** (config local de tooling) — pendiente menor: decidir si va a `.gitignore`. Fuente: `docs/ESTADO-PROYECTO.md`.

### Observaciones menores de auditoría (no bloqueantes)

- **COG-16:** el cortocircuito de escalación vive en un middleware de Telegram, no en el Director como indica el diseño original. Funciona, pero está en la capa equivocada. Fuente: `docs/INFORME_AUDITORIA.md`.
- **VIP-07:** la deduplicación de mensajes funciona pero tiene una ventana donde podrían colarse duplicados. Fuente: `docs/INFORME_AUDITORIA.md`.

---

## 6. Operativo / despliegue

- **Migraciones 027 / 028 / 029 en producción — pendiente de verificación (operativo).** Último snapshot verificado = `026` (2026-08-11). Apply de `027` (ephemeral), `028` (link) y `029` (feedback_quality) en producción SIN VERIFICAR. Fuente: `docs/ESTADO-PROYECTO.md`.
- **`needs_examples` — pendiente de investigación (operativo).** La capacidad está cableada en el código (Analyst → `planner.py` → `knowledge.examples` → evaluator); falta confirmar en los traces de producción que se activa en turnos reales y que el pool de H8 (4,348 ejemplos) genera retrievals efectivos. No es una brecha de implementación. Fuente: `docs/ANEXO-H.md`.

---

## Referencias

- `docs/ESTADO-PROYECTO.md` — estado actual del sistema y pendientes reales (2026-08-21).
- `docs/INFORME_AUDITORIA.md` — auditoría de alineamiento código ↔ REQUERIMIENTOS.md (161 reqs).
- `docs/SPEC-FASE5.md` — perfil de VIP con memoria; pendientes de privacidad y dedup (§12).
- `docs/SPEC-EVOLUCION-AGENTE.md` — evolución de agente (v1.2); fase 4 diferida y retención de datos.
- `docs/SPEC-FEEDBACK.md` — feedback de calidad; UI de edición de políticas pendiente.
- `docs/SPEC-FASE3.md`, `docs/MVP_COMPONENT_DESIGN.md` — autoenvío cableado tras flag; hot-swap LLM.
- `docs/ANEXO-H.md` — hitos H6-H9; `needs_examples` y saludo puro.
- `docs/CHECKLIST_ANILLO_OPERATIVO.md` — anillo operativo; F2 agenda parcial.

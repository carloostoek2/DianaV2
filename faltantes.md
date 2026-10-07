# Faltantes del sistema — catálogo consolidado

> Único punto de consulta de lo que **no está implementado o no está activo** en DianaV2 (2026-09-14).
> Lo que no aparece aquí está implementado y activo. Consolidado desde `docs/ESTADO-PROYECTO.md`,
> `docs/INFORME_AUDITORIA.md`, `docs/SPEC-FASE5.md`, `docs/SPEC-EVOLUCION-AGENTE.md`, `docs/SPEC-FEEDBACK.md`
> y `docs/ANEXO-H.md`. Sin lenguaje de implementación futura: cada ítem reporta su estado actual
> (no implementado / parcial / diferido por decisión de producto / deshabilitado / pendiente de verificación).

---

## 1. Auditoría de requerimientos

Ítems abiertos o diferidos de la auditoría de alineamiento código ↔ REQUERIMIENTOS.md (2026-07, re-verificada 2026-09-10). Fuente principal: `docs/INFORME_AUDITORIA.md`; también `docs/ESTADO-PROYECTO.md` §3.

| ID | Ítem | Estado | Fuente |
|---|---|---|---|
| AUTH-07 | Modo observación silenciosa de chats no-VIP (escuchar sin responder, solo para aprender): solo existe training mode que responde; no hay rama de observación pasiva | Diferido por decisión de producto (2026-08-22) (= brecha v1→v2 #12, ver §3) | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md` |
| GAP-08 | Comando/UI dedicado para listar/desactivar políticas de la tabla `policies`: `deactivate_policy` existe pero solo se usa en cleanup de fallo de regeneración de doctrina; el panel "Políticas de conducta" edita el catálogo de persona versionado (almacén distinto) | No implementado | `docs/INFORME_AUDITORIA.md`, `docs/SPEC-FEEDBACK.md` |
| MODE-09 | Feedback post-send autónomo dedicado: solo existe la corrección de turno (Destacar/Reprender); no hay calificador post-envío | No implementado | `docs/INFORME_AUDITORIA.md`, `docs/ESTADO-PROYECTO.md` |
| EVAL-04 | Visualización de calibración por dimensión: el resumen semanal muestra tasa global y drift, no tabla por dimensión | No implementado | `docs/INFORME_AUDITORIA.md` |

Nota: **AUTH-03** (tope configurable de VIPs) fue **descartado por producto (2026-08-22)**. GAP-11, REE-02/COG-15 (`RecontactPersonalizer`), ADM-03 (`HotSwapLLMProvider`) y EA-06 (historial de perfil) están cerrados / implementados y ya no figuran aquí. Recontacto personalizado está **implementado pero deshabilitado** (`FEATURE_RECONTACT_ENABLED=false` en `.env`) — ver §2.

---

## 2. Autonomía y evolución de agente

Fuente principal: `docs/SPEC-EVOLUCION-AGENTE.md` v1.2, `docs/SPEC-AUTONOMIA-CALIBRACION.md` y `docs/ESTADO-PROYECTO.md` §3.

- **Autoenvío autónomo (doble puerta) — deshabilitado.** `FEATURE_AUTONOMOUS_MODE=false` en `.env` (default en `settings.py`). `GLOBAL_MODE=supervised`. La ruta de envío autónomo está cableada tras el flag (`turn_orchestrator.py`, `recontact_service.py`) pero el kill-switch L1 la desactiva. En shadow solo se acumula medición; nada se autoenvía.
- **Autonomía fática real (carril rápido F2) más allá del saludo puro — no implementada.** El clasificador y el carril rápido están en shadow: clasifican y registran, no autoenvían. El saludo puro se resuelve con plantilla (`reason=plantilla_saludo`, sin Planner/Generator/Evaluator/Decider), no con envío autónomo personalizado. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` §Fase 2, `docs/ANEXO-H.md`.
- **Escalación forzada del detector emocional — no implementada.** La escalación del detector es shadow-only: se loguea y compara `pipeline_would_have_escalated`; no fuerza al Decider. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` (componente transversal).
- **Fila 4 — readiness / coincidencia / calidad / recomendación: código + flags de medición activos; autoenvío off.** En `.env`: `FEATURE_AUTONOMY_READINESS_ENABLED=true`, `FEATURE_AUTONOMY_COINCIDENCE_ENABLED=true`, `FEATURE_AUTONOMY_QUALITY_ENABLED=true`, `FEATURE_AUTONOMY_RECOMMENDATION_ENABLED=true`; el kill-switch de autoenvío sigue en `false`. PR #3 (vista borrador autonomía) merged en `main` (`5ff0b77`). Fuente: `docs/SPEC-AUTONOMIA-CALIBRACION.md`, `docs/ESTADO-PROYECTO.md`.
- **Recontacto personalizado (REE-02 / COG-15) — implementado pero deshabilitado.** `RecontactPersonalizer` existe; `FEATURE_RECONTACT_ENABLED=false` en `.env`.
- **Fase 4 de evolución de agente (iniciativa contextual) — diferida por decisión de producto.** Especificada en el spec; no confundir con la Fase 4 de Atención general, que sí está implementada. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` §Fase 4, `docs/ESTADO-PROYECTO.md`.

---

## 3. Brechas v1→v2 pendientes

Del análisis de brechas v1→v2 (los ítems resueltos se eliminaron de este catálogo). Fuente principal: este archivo antes de la consolidación y `docs/CHECKLIST_ANILLO_OPERATIVO.md`.

| Brecha | Estado | Fuente |
|---|---|---|
| #8 — Contexto temporal / rutina semanal: `ScheduleRetriever` listo (matching día/hora en America/Mexico_City, `knowledge.schedule`), pero la inyección es condicional — el Planner decide `needs_schedule`, no se inyecta en every prompt como en v1 | Parcial | brechas v1→v2, `docs/CHECKLIST_ANILLO_OPERATIVO.md` (F2) |
| #12 — Observación de mensajes no autorizados con persistencia: no existe el modo; los no-VIP van a training mode, promo o se descartan con log `auth_drop_not_allowed` | Diferido por producto (= AUTH-07, ver §1) | brechas v1→v2 |

---

## 4. Feedback de calidad

Fuente principal: `docs/SPEC-FEEDBACK.md`.

- **UI para editar manualmente el `trigger`/`rule` autogenerado de una política creada por reprimenda — no implementada.** Las políticas de reprimenda se guardan en la tabla `policies` del DB vía `promote_to_policy`; el `trigger` autogenerado queda tal como se creó, sin flujo de edición posterior. El panel "Políticas de conducta" (`persona_admin.py`) edita un almacén distinto (persona versionada en JSON). Relacionado con GAP-08 (§1).
- **Marcar dorado/reprimenda de forma retroactiva sobre historial ya entregado (vía `/traza`) — no implementado** (descartado en la sesión de diseño; fuera de alcance explícito).
- **Enganchar la reprimenda al `vip_trust_budget` del Evo-Agente (bajar confianza a la categoría del turno) — no implementado** (mencionado como extensión; fuera de alcance explícito). Nota: la migración `036_correction_severity` introduce decremento de trust por severidad en el flujo de corrección de turno; el enganche específico reprimenda→budget por categoría sigue sin UI/flujo dedicado.

---

## 5. Privacidad y deuda técnica

### Privacidad del backfill (nota de diseño, fix round F3 — hallazgo de security-auditor)

Durante el backfill, el historial completo del chat del VIP se envía al proveedor LLM externo (DeepSeek) para la extracción (comportamiento by-design, REQ-MEM-04). Controles actuales: ventana de 200 mensajes + tope de 12K caracteres por ventana + líneas truncadas a 400 caracteres, y ninguna escritura fuera de `memories`. El masking de PII al borde LLM está **activo** de forma general (`FEATURE_PII_MASKING_ENABLED`); pendientes específicos del backfill (`docs/SPEC-FASE5.md` §12.7):

- (a) flag de exclusión por VIP (opt-out del backfill) — no implementado.
- (b) evaluar redacción/masking de PII adicional cuando no sea necesaria para la extracción (ampliar a direcciones/CURP/RFC/nombres v2) — pendiente / parcial.
- (c) documentar retención y evaluar modelo local/on-prem para extracción sensible — no implementado.
- (d) confirmar acuerdo de procesamiento de datos con el proveedor — no implementado (guía en `docs/ACUERDO-PROVEEDOR-LLM.md`).

### Deuda técnica

- **Recalibración del umbral de dedup (0.85)** tras uso real — pendiente. Fuente: `docs/ESTADO-PROYECTO.md`, `docs/SPEC-FASE5.md`.
- **Calibración de deriva:** score 0.25 vs umbral 0.1 (esperado tras cambios de persona); re-anclar baseline en ~4 semanas — pendiente operativo. Fuente: `docs/ESTADO-PROYECTO.md`.
- **Política de purga/retención para tablas del Evo-Agente** (`vip_profile_history`, `turn_category_log`, `emotional_signal_log`, y tablas posteriores del camino a autonomía) — no definida; crecen sin límite. Fuente: `docs/SPEC-EVOLUCION-AGENTE.md` §Fase 0.
- **Calibración automática semanal — deshabilitada.** El job existe pero está gateado por `FEATURE_CALIBRATION_ENABLED=false` (default en `settings.py`, `false` en `.env`). Fuente: `docs/MVP_COMPONENT_DESIGN.md`, código (`main.py` job gate).
- **`reasonix.toml` untracked** (config local de tooling) — pendiente menor: decidir si va a `.gitignore`. Fuente: `docs/ESTADO-PROYECTO.md`.

### Observaciones menores de auditoría (no bloqueantes)

- **COG-16:** el cortocircuito de escalación vive en un middleware de Telegram, no en el Director como indica el diseño original. Funciona, pero está en la capa equivocada. Fuente: `docs/INFORME_AUDITORIA.md`.
- **VIP-07:** la deduplicación de mensajes funciona pero tiene una ventana donde podrían colarse duplicados. Fuente: `docs/INFORME_AUDITORIA.md`.

---

## 6. Operativo / despliegue

- **`needs_examples` — pendiente de investigación (operativo).** La capacidad está cableada en el código (Analyst → `planner.py` → `knowledge.examples` → evaluator); falta confirmar en los traces de producción que se activa en turnos reales y que el pool de H8 genera retrievals efectivos. No es una brecha de implementación. Fuente: `docs/ANEXO-H.md`.
- **Acuerdo con el proveedor de IA (DeepSeek):** pendiente de gestión de la dueña — guía en `docs/ACUERDO-PROVEEDOR-LLM.md`. No bloquea al bot (el masking ya está activo).

---

## 7. Historial de VIP (importación desde la cuenta personal)

Decisión de producto del **2026-09-06**, tomada al cambiar la cuenta de Telegram con la que
opera Diana. Las dos vías de importación quedaron apagadas a propósito, no por falla.

- **Recarga de historial de VIP ya registrados — apagada a propósito.**
  `FEATURE_HISTORY_REIMPORT_ENABLED=false` en `.env`. Motivo: la sesión de Telethon
  configurada (`TELETHON_SESSION_PATH`) es de la **cuenta anterior**, y la cuenta en uso **no
  tiene historial con ningún VIP** (todos escriben en chats nuevos). Recargar consultaría
  Telegram con una cuenta que ya no opera y, además, generaría actividad de una cuenta recién
  creada, con el riesgo de llamar la atención de Telegram. El historial anterior **sigue
  guardado** en `message_history`: no se borró nada.
- **Importación de historial al registrar un VIP nuevo — apagada a propósito.**
  `FEATURE_VIP_HISTORY_SEED_ENABLED=false` en `.env` (misma fecha y mismo motivo). Antes de
  este cambio, cada alta disparaba un intento de importación en segundo plano con la sesión de
  la cuenta anterior (no bloqueaba el alta) y avisaba a la dueña con un mensaje que podía
  leerse como "no había historial" cuando en realidad la sesión era de otra cuenta. Ahora el
  alta no toca Telethon y deja registrado el motivo.
- **Condición para reactivar cualquiera de las dos:** que `TELETHON_SESSION_PATH` apunte a una
  sesión de la **cuenta en uso** y que la dueña decida de forma explícita asumir el riesgo de
  que Telegram note la actividad de la cuenta. No hay reactivación automática ni por fecha.
- **Qué se pierde mientras estén apagadas:** Diana no recupera la conversación previa de un VIP
  al registrarlo (arranca sin contexto de ese chat) ni reprocesa el historial ya guardado para
  reconstruir perfiles. La captura de historial en vivo (lo que la dueña escribe en el chat del
  VIP) sigue funcionando con normalidad.
- **Detalle técnico y evidencia:** `audit/FASE2-HISTORIAL.md`.

---

## Referencias

- `docs/ESTADO-PROYECTO.md` — estado actual del sistema y pendientes reales (2026-09-14).
- `audit/FASE2-HISTORIAL.md` — decisión del historial desde la cuenta personal (2026-09-06) y verificación del alta de VIP.
- `docs/INFORME_AUDITORIA.md` — auditoría de alineamiento código ↔ REQUERIMIENTOS.md (161 reqs).
- `docs/SPEC-FASE5.md` — perfil de VIP con memoria; pendientes de privacidad y dedup (§12).
- `docs/SPEC-EVOLUCION-AGENTE.md` — evolución de agente (v1.2); fase 4 diferida y retención de datos.
- `docs/SPEC-AUTONOMIA-CALIBRACION.md` — Fila 4 / camino a la autonomía.
- `docs/SPEC-FEEDBACK.md` — feedback de calidad; UI de edición de políticas pendiente.
- `docs/SPEC-FASE3.md`, `docs/MVP_COMPONENT_DESIGN.md` — autoenvío cableado tras flag; hot-swap LLM.
- `docs/ANEXO-H.md` — hitos H6-H9; `needs_examples` y saludo puro.
- `docs/CHECKLIST_ANILLO_OPERATIVO.md` — anillo operativo; F2 agenda parcial.

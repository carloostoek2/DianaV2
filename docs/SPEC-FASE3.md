
SPEC-FASE3.md — Producto Completo (Autonomía, Proactividad y Métricas) — VERSIÓN ACTUALIZADA

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Contrato de diseño e implementación para la Fase 3
Basado en SPEC.md v1.5, SPEC-FASE2.md v2.1, Anexo T (Trazabilidad)
Audiencia Ingeniería
Versión 3.1 — Revisión Post-Review
Estado Aprobado para implementación (sobre base de Fase 2 + Trazabilidad)

---

Resumen de Cambios respecto a v3.0

Sección Cambio
4.2 Unificar umbrales autónomos a 0.9/0.8/0.7 (conservadores para arranque).
5.3 Añadir is_blocked() y verificación en execute_recontact() y get_due_vips().
5.5 Añadir regla de margen mínimo en CalibrationService (autónomo >= supervisado + 0.05).
6.2 Actualizar flujo de recontacto con filtros de exclusión (REQ-REE-03, BR-05).
6.3 Añadir tabla promo_executions, lógica de diferenciación (REQ-PRO-03) y trazabilidad.
8 Añadir hook de cancelación de recontacto en TurnCoordinator (BR-07).
11 Eliminar duplicación de umbrales; añadir decisiones abiertas sobre márgenes y promos.

---

1. Propósito de esta Fase

Completar el sistema con las capacidades que lo convierten en un producto final listo para producción:

1. Modo autónomo: El sistema puede enviar respuestas sin aprobación previa, sujeto a umbrales de confianza y configuraciones por VIP.
2. Recontacto por silencio: El sistema puede iniciar conversaciones proactivamente cuando un VIP lleva tiempo sin interactuar, respetando estados bloqueantes (REQ-REE-03, BR-05).
3. Promo no-VIP: Respuesta automática a mensajes de contacto no autorizados con una secuencia promocional fija, diferenciando primer envío de reenvío (REQ-PRO-03) y con trazabilidad.
4. Calibración automática de umbrales: Ajuste dinámico de los umbrales del Evaluador y Decisor basado en datos históricos de corrección, con garantía de que el umbral autónomo siempre sea más estricto que el supervisado.
5. Behavior Engine avanzado: Mensajes divididos, errores humanos simulados, y secuencias multi-mensaje.
6. Métricas completas de aprendizaje: Dashboards agregados para medir efectividad, drift de estilo y repetición de zona gris.

---

2. Alcance de la Fase 3

2.1 Dentro de alcance

ID Área
F3-01 Modo autónomo global y por VIP (auto-envío) con notificaciones opcionales.
F3-02 Decisor actualizado para emitir send en modo autónomo (respetando umbrales).
F3-03 Recontacto por silencio con pipeline reducido y plantillas fijas, excluyendo estados bloqueantes (pausa, congelación, aprobación pendiente, sandbox).
F3-04 Promo no-VIP por trigger exacto (secuencia multi-mensaje sin LLM), diferenciando primer envío de reenvío y con trazabilidad ligera.
F3-05 Calibración automática de umbrales basada en tasa de corrección real, manteniendo margen autónomo > supervisado.
F3-06 Behavior Engine avanzado: mensajes divididos, simulaciones de errores humanos, secuencias multi-mensaje.
F3-07 Métricas agregadas semanales: tasa de aprobación sin corrección, repetición de zona gris, falsos positivos de escalación, drift de estilo.
F3-08 Dashboard de métricas en el DM (resumen semanal).
F3-09 Hook de cancelación de recontacto en TurnCoordinator cuando el VIP escribe.

2.2 Fuera de alcance (postergado)

ID Exclusión
F3-O1 Multi-tenant (varias dueñas en la misma instancia).
F3-O2 Canales distintos de Telegram Business (WhatsApp, etc.).
F3-O3 Integración con CRM o pasarela de pagos.
F3-O4 Panel web avanzado (todo permanece en el DM).

---

3. Feature Toggles (Nuevos y existentes)

Añadir los siguientes flags a system_config. Todos con valor por defecto false para mantener compatibilidad con Fase 2.

Flag Descripción Valor en Fase 3
FEATURE_AUTONOMOUS_MODE Habilita el envío directo sin aprobación (global). true (después de pruebas)
FEATURE_RECONTACT_ENABLED Habilita el recontacto por silencio. true
FEATURE_PROMO_ENABLED Habilita la respuesta promocional a no-VIP. true
FEATURE_CALIBRATION_ENABLED Habilita el ajuste automático de umbrales. true
FEATURE_ADVANCED_BEHAVIOR Habilita mensajes divididos y errores humanos simulados. true

Regla: Cada nuevo comportamiento debe estar envuelto en su flag correspondiente. Si un flag está desactivado, el sistema se comporta como en Fase 2.

---

4. Extensiones al Modelo de Datos

4.1 Tablas nuevas o extendidas

```sql
-- Recontacto programado
CREATE TABLE recontact_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vip_id          UUID NOT NULL REFERENCES vips(id) ON DELETE CASCADE,
    last_contact_at TIMESTAMPTZ NOT NULL,
    next_contact_at TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | done | cancelled
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON recontact_schedules (next_contact_at, status);

-- Promo no-VIP (trigger exacto + secuencia)
CREATE TABLE promo_triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_text    TEXT NOT NULL UNIQUE,  -- texto exacto que dispara la promo
    response_sequence JSONB NOT NULL,      -- lista de mensajes (strings)
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trazabilidad de ejecuciones de promo (NUEVA)
CREATE TABLE promo_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id         BIGINT NOT NULL,
    trigger_id      UUID NOT NULL REFERENCES promo_triggers(id),
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    sequence_sent   JSONB,  -- opcional: copia de lo que se envió
    status          TEXT NOT NULL DEFAULT 'sent'  -- sent | failed
);
CREATE INDEX ON promo_executions (chat_id, trigger_id, sent_at DESC);

-- Métricas agregadas (ya existe learning_metrics, se usa ahora)
ALTER TABLE learning_metrics ADD COLUMN style_drift_score REAL;
```

4.2 Configuraciones adicionales en system_config

Unificado: Los umbrales autónomos iniciales son conservadores para el arranque en frío (0.9/0.8/0.7). La calibración automática los ajustará tras acumular suficientes datos.

```json
{
  "autonomous_thresholds": {
    "safety_min": 0.9,
    "doctrine_min": 0.8,
    "naturalness_min": 0.7
  },
  "supervised_thresholds": {
    "safety_min": 0.5,
    "doctrine_min": 0.4,
    "naturalness_min": 0.5
  },
  "calibration": {
    "enabled": true,
    "window_days": 30,
    "min_samples": 50,
    "autonomous_margin_min": 0.05
  },
  "recontact": {
    "inactivity_days": 7,
    "templates": ["Hola {nombre}, ¿cómo has estado? ..."]
  },
  "promo": {
    "triggers": ["quiero información", "promociones", "precios"],
    "sequence": ["Mensaje 1", "Mensaje 2", "Mensaje 3"],
    "repeat_days": 30   # días que deben pasar para reenviar la misma promo al mismo chat
  },
  "behavior": {
    "allow_split": true,
    "allow_human_quirks": true,
    "typing_speed_chars_per_second": 30,
    "split_chars": 4096
  }
}
```

---

5. Contratos de los Nuevos Componentes

5.1 Decisor (extensión para modo autónomo)

Se añade una nueva regla al final de la tabla de prioridades, después de las reglas existentes (Anexo F y SPEC-FASE2 actualizado):

Prioridad Condición Acción bruta Filtro de modo Acción final
5 Modo autónomo activo Y perfil.seguridad >= umbral_autonomo_seguridad Y perfil.doctrina >= umbral_autonomo_doctrina Y perfil.naturalidad >= umbral_autonomo_naturalidad Enviar autonomo → Enviar Enviar
6 Modo autónomo activo pero no cumple umbrales Aprobar supervisado → Aprobar Aprobar (fallback a supervisado)

Nota: Los umbrales autónomos siempre son más altos que los de supervisado (garantizado por la calibración). El orden de prioridades (seguridad → zona gris → risk alto → regenerar → send → approve) se mantiene como en Fase 2.

5.2 AutonomousModeService

```python
class AutonomousModeService:
    async def is_autonomous_enabled(vip_id: UUID | None = None) -> bool:
        """Retorna True si el modo autónomo está activo para el VIP (o global)."""
        # Si vip_id tiene auto_send=True, prevalece sobre el global.
    
    async def notify_if_needed(turn_id: UUID, decision: Decision, evaluation: EvaluationProfile) -> None:
        """Notifica a la dueña solo si alguna dimensión está cerca del umbral (aviso)."""
```

5.3 RecontactService (extendido con verificación de bloqueo)

```python
class RecontactService:
    async def schedule_recontact(vip_id: UUID) -> None:
        """Programa el próximo recontacto basado en la última interacción."""
    
    async def execute_recontact(vip_id: UUID) -> None:
        """Ejecuta el pipeline reducido para generar un mensaje de recontacto."""
        # Verifica que el VIP no esté en estado bloqueante (REQ-REE-03)
        if await self.is_blocked(vip_id):
            return
        # ... resto del flujo
    
    async def cancel_recontact(vip_id: UUID) -> None:
        """Cancela un recontacto programado (ej. cuando el VIP escribe)."""
    
    async def is_blocked(vip_id: UUID) -> bool:
        """Retorna True si el VIP está en pausa, congelado, con aprobación pendiente, o en sandbox."""
        # Consulta:
        # - vips.paused_until > now()
        # - EXISTS gray_zone_queries WHERE status='open'
        # - EXISTS turns WHERE status='pending_approval'
        # - vips.is_sandbox = true
    
    async def get_due_vips() -> List[UUID]:
        """Retorna VIPs elegibles para recontacto (excluyendo bloqueados)."""
        # Query que filtra por:
        # - last_contact_at < now() - inactivity_days
        # - NOT is_blocked (pausa, frozen, sandbox, etc.)
        # - NO recontacto pendiente
```

Pipeline reducido de recontacto:

· No pasa por Analista ni Planificador.
· Solo recupera memory y policy (si las hay).
· Genera un mensaje usando una plantilla base + personalización.
· Pasa por Evaluador (pero con umbrales más laxos).
· Si modo autónomo, se envía directamente; si supervisado, se envía a aprobación.

5.4 PromoService (extendido con trazabilidad y diferenciación)

```python
class PromoService:
    async def match_trigger(text: str) -> Optional[PromoTrigger]:
        """Busca coincidencia exacta en promo_triggers."""
    
    async def has_recent_execution(chat_id: int, trigger_id: UUID, days: int = 30) -> bool:
        """Verifica si el chat ya recibió esta promo en los últimos N días."""
    
    async def execute_promo(chat_id: int, trigger: PromoTrigger) -> None:
        """Envía la secuencia de mensajes usando BehaviorEngine."""
        # 1. Verificar si ya se envió (REQ-PRO-03)
        if await self.has_recent_execution(chat_id, trigger.id):
            return  # o enviar mensaje breve alternativo
        # 2. Enviar secuencia
        # 3. Registrar en promo_executions
```

Reglas:

· No usa LLM en ningún paso.
· La secuencia se envía con delays y typing entre mensajes.
· No se guarda en pipeline_traces (no es un turno cognitivo), pero se guarda en promo_executions para trazabilidad.
· Primer envío vs reenvío: si ya recibió la promo en los últimos promo.repeat_days días, no se reenvía (o se envía un mensaje breve).

5.5 CalibrationService (extendido con garantía de margen)

```python
class CalibrationService:
    async def calibrate_thresholds(window_days: int = 30) -> None:
        """Recalcula umbrales basados en la tasa de corrección real."""
        # 1. Recupera todos los turnos del período con evaluación y corrección (o no)
        # 2. Para cada dimensión, calcula el percentil donde la tasa de corrección es baja
        #    (supervisado) y donde es aún más baja (autónomo)
        calibrated_supervised = self._calculate_percentiles(window_days, target_percentile=0.7)
        calibrated_autonomous = self._calculate_percentiles(window_days, target_percentile=0.9)
        
        # 3. Garantizar relación: autónomo >= supervisado + margen_mínimo (0.05)
        MARGIN = system_config.get("calibration.autonomous_margin_min", 0.05)
        final_autonomous = {
            dim: max(calibrated_autonomous[dim], calibrated_supervised[dim] + MARGIN)
            for dim in calibrated_autonomous
        }
        
        # 4. Actualiza system_config con nuevos umbrales (ambos conjuntos)
        # 5. Registra cambio con timestamp para auditoría
    
    async def detect_drift() -> Dict[str, float]:
        """Compara estilo actual con el histórico para detectar drift."""
```

5.6 BehaviorEngine (extensión avanzada)

Se añaden nuevas capacidades al BehaviorEngine:

```python
class DeliveryContext:
    # ... campos existentes ...
    allow_split: bool = False          # si True, puede dividir el mensaje en varios
    allow_human_quirks: bool = False   # si True, puede añadir errores leves o pausas
    split_chars: int = 4096            # límite de caracteres por mensaje

class BehaviorEngine:
    async def deliver_with_sequence(texts: list[str], ctx: DeliveryContext) -> DeliveryResult:
        """Envía una secuencia de mensajes con delays entre ellos."""
        # Similar a deliver(), pero itera sobre la lista y respeta delays entre mensajes.
```

---

6. Flujos Canónicos de Fase 3

6.1 Turno VIP en modo autónomo

```
business_message
  → TurnCoordinator (igual)
  → Director (pipeline completo)
  → Decisor:
      - Si safety baja → escalate
      - Si needs_policy + sin política → consult_doctrine (zona gris)
      - Si risk=alto → escalate
      - Si FEATURE_AUTONOMOUS_MODE y umbrales superados → send
      - Si no → approve (fallback a supervisado)
  → Si action = "send":
      → BehaviorEngine.deliver() directamente
      → Notificación a la dueña (opcional, si alguna dimensión está cerca del umbral)
      → Learning post-turno (registra traza, Staging si corrección posterior)
  → Si action = "approve":
      → Flujo supervisado normal (como en Fase 1/2)
  → Si action = "consult_doctrine" o "escalate":
      → Flujos de Fase 2
```

6.2 Recontacto por silencio (job programado) — ACTUALIZADO

```
Job programado (ej. cada hora):
  → RecontactService.get_due_vips()
      → Filtra por:
          - last_contact_at < now() - inactivity_days
          - paused_until IS NULL OR paused_until < now()
          - NOT EXISTS (gray_zone_queries WHERE status='open')
          - NOT EXISTS (turns WHERE status='pending_approval')
          - is_sandbox = false
          - NOT EXISTS (recontact_schedules WHERE status='pending')
  → Para cada VIP:
      → RecontactService.execute_recontact(vip_id)
          → Verifica nuevamente is_blocked() (protección contra condiciones de carrera)
          → Director (pipeline reducido):
              - NO pasa por Analista ni Planificador
              - Recupera memory y policy (si las hay)
              - Genera mensaje con plantilla base + personalización
              - Evaluador (umbrales más laxos)
              - Decisor (solo send o approve, nunca consult_doctrine/escalate)
          → Si send → BehaviorEngine.deliver()
          → Si approve → cola de aprobación de la dueña
      → Programar próximo recontacto (según configuración)
```

Reglas de exclusión (REQ-REE-03, BR-05):

· No hay recontacto si el VIP está congelado (zona gris abierta).
· No hay recontacto si el VIP tiene una aprobación pendiente.
· No hay recontacto si el VIP está en pausa de datos.
· No hay recontacto si el VIP está en sandbox.
· No hay recontacto si ya hay un recontacto programado pendiente.

6.3 Promo no-VIP (trigger exacto) — ACTUALIZADO

```
business_message de no-VIP (no está en allowlist)
  → Middleware de auth detecta no-VIP
  → PromoService.match_trigger(texto)
  → Si match:
      → Verificar si este chat ya recibió esta promo en los últimos `promo.repeat_days` días
          → Si ya recibió → NO reenviar (silenciosamente o enviar mensaje breve)
          → Si es primera vez → continuar
      → PromoService.execute_promo(chat_id, trigger)
          → BehaviorEngine.deliver_with_sequence(sequence, ctx)
          → Registrar en promo_executions (chat_id, trigger_id, sent_at, sequence_sent)
      → No se guarda en pipeline_traces
  → Si no match:
      → Ignorar (no se responde)
```

Diferenciación primer envío vs reenvío (REQ-PRO-03):

· Si es primera vez → enviar secuencia completa.
· Si ya fue enviado → no enviar nada (o enviar un mensaje breve "ya te enviamos información").
· Configurable por despliegue (ej. promo.repeat_days = 30).

Trazabilidad (REQ-MET y filosofía Anexo T):

· promo_executions permite auditar cuántas veces se envió cada promo, a qué chats, y cuándo.
· No se guarda el pipeline completo, pero hay registro de ejecución.

6.4 Calibración automática (job semanal)

```
Job programado (ej. cada domingo a las 3 AM):
  → Si FEATURE_CALIBRATION_ENABLED:
      → CalibrationService.calibrate_thresholds(window_days=30)
          - Calcula umbrales supervisados (percentil 70)
          - Calcula umbrales autónomos (percentil 90)
          - Aplica margen mínimo: autónomo >= supervisado + 0.05
          - Actualiza system_config
      → CalibrationService.detect_drift()
          - Compara estilo actual con línea base
          - Si drift > umbral, notifica a la dueña
      → Registra en learning_metrics
      → Notifica a la dueña con resumen
```

6.5 Hook de cancelación de recontacto en TurnCoordinator — NUEVO

Cuando llega un nuevo business_message de un VIP, el TurnCoordinator debe:

1. Antes de crear o reemplazar un turno, llamar a RecontactService.cancel_recontact(vip_id).
2. Esto asegura que cualquier recontacto programado se cancele si el VIP escribe activamente (BR-07, comportamiento natural).

```python
# En TurnCoordinator.ensure_valid_turn()
async def ensure_valid_turn(chat_id: int, message: Message) -> Turn:
    vip_id = await self.get_vip_id(chat_id)
    if vip_id and FEATURE_RECONTACT_ENABLED:
        await self.recontact_service.cancel_recontact(vip_id)
    # ... resto del flujo
```

6.6 Mensajes divididos (Behavior avanzado)

```
Cuando se envía un mensaje largo:
  → BehaviorEngine.deliver() verifica ctx.allow_split
  → Si True y len(texto) > split_chars:
      → Divide el texto en segmentos (por puntos, comas o saltos de línea)
      → Envía cada segmento con delays intermedios y typing
  → Si False, envía como un solo mensaje (podría truncarse según límite de Telegram)
```

---

7. Métricas y Calibración

7.1 Métricas agregadas (tabla learning_metrics)

Cada semana se guarda un registro con:

Campo Descripción
week_start Fecha de inicio de la semana (lunes).
total_turns Número total de turnos procesados.
approval_without_correction_rate Proporción de turnos aprobados sin corrección.
gray_zone_repetition_count Número de veces que se abrió zona gris para un mismo trigger.
false_positive_escalation_rate Proporción de escalaciones que la dueña marcó como falsas.
style_drift_score Métrica de drift de estilo (comparación de embeddings de respuestas con las primeras semanas).
autonomous_send_rate Proporción de turnos enviados en modo autónomo (sin aprobación).
average_latency_ms Latencia promedio del pipeline.

7.2 Detección de drift de estilo (REQ-MET-04)

· Cada semana, se selecciona una muestra aleatoria de respuestas generadas (ej. 50).
· Se calcula el embedding promedio de la muestra y se compara con el embedding promedio de las primeras 4 semanas (línea base).
· Si la distancia coseno supera un umbral (ej. 0.1), se registra un style_drift_score alto.
· La dueña recibe una alerta si el drift es significativo: "El estilo de respuesta ha cambiado; revisa las últimas conversaciones."

7.3 Dashboard en el DM

La dueña puede consultar un resumen con:

```
📊 Resumen de aprendizaje (semana del 25/07 al 31/07):
- Turnos totales: 142
- Aprobación sin corrección: 78% (↑ 5% vs semana anterior)
- Repetición de zona gris: 3 (mismos triggers: "precios")
- Falsos positivos de escalación: 2 (↓ 50%)
- Drift de estilo: 0.03 (normal)
- Envíos autónomos: 45 (32% del total)
- Promos enviadas: 12 (únicos: 10, repetidos: 2)

[📥 Exportar datos] [🔙 Volver]
```

---

8. Integración con Fases Anteriores

Fase Cambios necesarios en Fase 3
Fase 1 El Director y el Decisor se extienden para manejar send y el nuevo orden de prioridades. El Behavior Engine se actualiza con nuevas capacidades (split, quirks).
Fase 2 El GrayZoneService y StagingService se mantienen. La zona gris ahora puede activarse también en modo autónomo (si el Decisor decide consult_doctrine en lugar de send). La calibración usa datos de corrección de Staging.
Trazabilidad Las métricas y la calibración usan los datos de pipeline_traces; se añaden campos de timings y corrección. El dashboard muestra las métricas.
Recontacto NUEVO: Hook de cancelación en TurnCoordinator (cancel_recontact cuando el VIP escribe).

Compatibilidad: Todos los nuevos comportamientos están envueltos en feature flags, por lo que la Fase 3 puede activarse gradualmente sin romper Fase 2.

---

9. Roadmap de Implementación

Hito Descripción Dependencias
H3.1 Extender el Decisor con reglas de modo autónomo y umbrales. Feature flag FEATURE_AUTONOMOUS_MODE.
H3.2 Implementar AutonomousModeService y notificaciones opcionales. H3.1
H3.3 Implementar RecontactService con verificación de bloqueo y job programado. Tabla recontact_schedules, feature flag.
H3.4 Implementar PromoService con trazabilidad (tabla promo_executions) y diferenciación. Tablas promo_triggers, promo_executions.
H3.5 Implementar CalibrationService con margen mínimo autónomo > supervisado. Tabla learning_metrics, feature flag.
H3.6 Extender BehaviorEngine con mensajes divididos y quirks humanos. Feature flag FEATURE_ADVANCED_BEHAVIOR.
H3.7 Implementar job semanal de cálculo de métricas y drift. H3.5
H3.8 Añadir hook de cancelación de recontacto en TurnCoordinator. H3.3
H3.9 Añadir comandos de admin para ver métricas y configurar promos/recontactos. H3.3, H3.4, H3.7
H3.10 Pruebas de integración y activación gradual de flags. Todos los anteriores

---

10. Trazabilidad REQ → Componentes de Fase 3

Bloque REQ Componente(s)
REQ-MODE-02, 07, 08, 09 AutonomousModeService, Decisor, notificaciones
REQ-REE-01..04 RecontactService, job programado, pipeline reducido, hook de cancelación, exclusión de bloqueos
REQ-PRO-01..04 PromoService, trigger exacto, BehaviorEngine, diferenciación primer envío/reenvío, trazabilidad
REQ-EVAL-02..04 CalibrationService, ajuste de umbrales, margen autónomo > supervisado
REQ-MET-01..04 LearningMetrics, drift detection, dashboard
REQ-HUM-04..06 BehaviorEngine avanzado (split, quirks)
BR-05 Exclusión de pausa en recontacto
BR-07 Hook de cancelación de recontacto cuando dueña escribe

---

11. Decisiones de Diseño Abiertas (actualizadas)

1. Umbrales iniciales para modo autónomo: seguridad=0.9, doctrina=0.8, naturalidad=0.7 (definidos en 4.2). Se ajustarán automáticamente tras la primera calibración.
2. Frecuencia de calibración: Semanal (domingo 3 AM) con ventana de 30 días.
3. Margen mínimo autónomo-supervisado: 0.05 (configurable en calibration.autonomous_margin_min).
4. Duración de no repetición de promo: 30 días (configurable en promo.repeat_days).
5. Acción por defecto ante expiración de zona gris: "escalate" (seguridad).
6. Inactividad para recontacto: 7 días (configurable en recontact.inactivity_days).
7. Acción al reenviar promo ya enviada: Silencio (no reenviar) o mensaje breve "ya te enviamos información". Se recomienda silencio para no spamear.

---

12. Relación con Anexos y Documentos

Documento Relación
SPEC.md v1.5 El Director y el Behavior Engine se extienden; el Decisor añade nuevas reglas.
SPEC-FASE2.md La zona gris y staging se integran con el modo autónomo; la calibración usa datos de corrección.
Anexo T (Trazabilidad) Las métricas y la calibración usan pipeline_traces; las promos tienen su propia trazabilidad ligera.
Anexos_contratos.md El Decisor (Anexo F) se actualiza; Behavior Engine (Anexo I) se extiende.
AGENTS.md Actualizado con flujos de Fase 3, hooks y reglas de exclusión.

---

13. Notas Finales

· Gradualidad: Esta fase es la más compleja. Se recomienda activar los flags uno a uno: primero Recontacto (menos riesgoso, pero con filtros de bloqueo), luego Promo (bajo riesgo), luego Calibración (requiere datos), luego Modo Autónomo (después de calibración), y finalmente Behavior avanzado.
· Monitoreo: La dueña debe recibir notificaciones semanales con métricas para tener visibilidad del rendimiento.
· Rollback: Todos los nuevos comportamientos tienen feature flags; se puede desactivar cualquier funcionalidad sin redeploy.
· Cancelación de recontacto: El hook en TurnCoordinator asegura que el recontacto se cancele cuando el VIP escribe, evitando mensajes redundantes o inapropiados.

---

Fin del SPEC-FASE3.md (v3.1)
Última actualización: Julio 2026
Equipo de Arquitectura — Producto completo listo para desarrollo, con todas las correcciones del review integradas.

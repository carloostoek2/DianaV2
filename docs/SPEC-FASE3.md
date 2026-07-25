
SPEC-FASE3.md — Producto Completo (Autonomía, Proactividad y Métricas)

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Contrato de diseño e implementación para la Fase 3
Basado en SPEC.md v1.5, SPEC-FASE2.md v2.1, Anexo T (Trazabilidad)
Audiencia Ingeniería
Versión 3.0 — Producto Completo
Estado Pendiente de implementación (sobre base de Fase 2 + Trazabilidad)

---

Índice

1. Propósito de esta Fase
2. Alcance de la Fase 3
3. Feature Toggles (Nuevos y existentes)
4. Extensiones al Modelo de Datos
5. Contratos de los Nuevos Componentes
6. Flujos Canónicos de Fase 3
7. Métricas y Calibración
8. Integración con Fases Anteriores
9. Roadmap de Implementación
10. Trazabilidad REQ → Componentes
11. Decisiones de Diseño Abiertas
12. Relación con Anexos y Documentos
13. Notas Finales

---

1. Propósito de esta Fase

Completar el sistema con las capacidades que lo convierten en un producto final listo para producción:

1. Modo autónomo: El sistema puede enviar respuestas sin aprobación previa, sujeto a umbrales de confianza y configuraciones por VIP.
2. Recontacto por silencio: El sistema puede iniciar conversaciones proactivamente cuando un VIP lleva tiempo sin interactuar.
3. Promo no-VIP: Respuesta automática a mensajes de contacto no autorizados con una secuencia promocional fija.
4. Calibración automática de umbrales: Ajuste dinámico de los umbrales del Evaluador y Decisor basado en datos históricos de corrección.
5. Behavior Engine avanzado: Mensajes divididos, errores humanos simulados, y secuencias multi-mensaje.
6. Métricas completas de aprendizaje: Dashboards agregados para medir efectividad, drift de estilo y repetición de zona gris.

---

2. Alcance de la Fase 3

2.1 Dentro de alcance

ID Área
F3-01 Modo autónomo global y por VIP (auto-envío) con notificaciones opcionales.
F3-02 Decisor actualizado para emitir send en modo autónomo (respetando umbrales).
F3-03 Recontacto por silencio con pipeline reducido y plantillas fijas.
F3-04 Promo no-VIP por trigger exacto (secuencia multi-mensaje sin LLM).
F3-05 Calibración automática de umbrales del Evaluador y Decisor basada en tasa de corrección real.
F3-06 Behavior Engine avanzado: mensajes divididos, simulaciones de errores humanos, secuencias multi-mensaje.
F3-07 Métricas agregadas semanales: tasa de aprobación sin corrección, repetición de zona gris, falsos positivos de escalación, drift de estilo.
F3-08 Dashboard de métricas en el DM (resumen semanal).
F3-09 Exportación de datos de aprendizaje (opcional).

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

-- Métricas agregadas (ya existe learning_metrics, se usa ahora)
-- Se añade columna para drift detection:
ALTER TABLE learning_metrics ADD COLUMN style_drift_score REAL;
```

4.2 Configuraciones adicionales en system_config

```json
{
  "autonomous_thresholds": {
    "safety_min": 0.8,
    "doctrine_min": 0.7,
    "naturalness_min": 0.6
  },
  "recontact": {
    "inactivity_days": 7,
    "templates": ["Hola {nombre}, ¿cómo has estado? ..."]
  },
  "promo": {
    "triggers": ["quiero información", "promociones", "precios"],
    "sequence": ["Mensaje 1", "Mensaje 2", "Mensaje 3"]
  },
  "calibration": {
    "enabled": true,
    "window_days": 30,
    "min_samples": 50
  },
  "behavior": {
    "allow_split": true,
    "allow_human_quirks": true,
    "typing_speed_chars_per_second": 30
  }
}
```

---

5. Contratos de los Nuevos Componentes

5.1 Decisor (extensión para modo autónomo)

Se añade una nueva regla al final de la tabla de prioridades, después de las reglas existentes (Anexo F):

Prioridad Condición Acción bruta Filtro de modo Acción final
5 Modo autónomo activo Y perfil.seguridad >= umbral_autonomo_seguridad Y perfil.doctrina >= umbral_autonomo_doctrina Y perfil.naturalidad >= umbral_autonomo_naturalidad Enviar autonomo → Enviar Enviar
6 Modo autónomo activo pero no cumple umbrales Aprobar supervisado → Aprobar Aprobar (cae al modo supervisado como fallback)

Nota: Los umbrales autónomos son más altos que los de supervisado. Se calibran automáticamente en Fase 3.

5.2 AutonomousModeService

```python
class AutonomousModeService:
    async def is_autonomous_enabled(vip_id: UUID | None = None) -> bool:
        """Retorna True si el modo autónomo está activo para el VIP (o global)."""
        # Si vip_id tiene auto_send=True, prevalece sobre el global.
    
    async def notify_if_needed(turn_id: UUID, decision: Decision, evaluation: EvaluationProfile) -> None:
        """Notifica a la dueña solo si alguna dimensión está cerca del umbral (aviso)."""
```

5.3 RecontactService

```python
class RecontactService:
    async def schedule_recontact(vip_id: UUID) -> None:
        """Programa el próximo recontacto basado en la última interacción."""
    
    async def execute_recontact(vip_id: UUID) -> None:
        """Ejecuta el pipeline reducido para generar un mensaje de recontacto."""
    
    async def cancel_recontact(vip_id: UUID) -> None:
        """Cancela un recontacto programado (ej. si el VIP escribe antes)."""
```

Pipeline reducido de recontacto:

· No pasa por Analista ni Planificador.
· Solo recupera memory y policy (si las hay).
· Genera un mensaje usando una plantilla base + personalización.
· Pasa por Evaluador (pero con umbrales más laxos).
· Si modo autónomo, se envía directamente; si supervisado, se envía a aprobación.

5.4 PromoService

```python
class PromoService:
    async def match_trigger(text: str) -> Optional[PromoTrigger]:
        """Busca coincidencia exacta en promo_triggers."""
    
    async def execute_promo(chat_id: int, trigger: PromoTrigger) -> None:
        """Envía la secuencia de mensajes usando BehaviorEngine."""
```

Reglas:

· No usa LLM en ningún paso.
· La secuencia se envía con delays y typing entre mensajes.
· No se guarda en pipeline_traces (no es un turno cognitivo).

5.5 CalibrationService

```python
class CalibrationService:
    async def calibrate_thresholds(window_days: int = 30) -> None:
        """Recalcula umbrales basados en la tasa de corrección real."""
        # 1. Recupera todos los turnos del período con evaluación y corrección (o no)
        # 2. Para cada dimensión, calcula el percentil donde la tasa de corrección es baja
        # 3. Actualiza system_config con nuevos umbrales
    
    async def detect_drift() -> Dict[str, float]:
        """Compara estilo actual con el histórico para detectar drift."""
```

Algoritmo de calibración:

· Para cada dimensión (seguridad, doctrina, naturalidad, etc.), se calcula:
  · La distribución de valores en turnos aprobados sin corrección.
  · La distribución en turnos corregidos.
· El nuevo umbral se sitúa en el percentil que maximiza la precisión (ej. donde la tasa de falsos positivos y falsos negativos se equilibra).
· Se aplica un suavizado (promedio con umbral anterior) para evitar oscilaciones bruscas.
· La calibración se ejecuta automáticamente cada semana (job programado).

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

Mecanismo de división:

· Si allow_split=True y el texto supera split_chars, se divide en frases (por puntos, comas, o saltos de línea) y se envían como mensajes separados.
· Se simula "escribiendo…" entre cada mensaje.

Errores humanos simulados (quirks):

· Si allow_human_quirks=True, con una probabilidad baja (ej. 5%) se puede:
  · Añadir una pausa extra (más allá del delay normal).
  · Corregir un error tipográfico (ej. enviar un mensaje y luego un "corrección: ...").
  · Dividir un mensaje de forma "natural" (cortar en medio de una frase).

---

6. Flujos Canónicos de Fase 3

6.1 Turno VIP en modo autónomo

```
business_message
  → TurnCoordinator (igual)
  → Director (pipeline completo)
  → Decisor:
      - Si FEATURE_AUTONOMOUS_MODE y umbrales superados → action = "send"
      - Si no → action = "approve" (fallback a supervisado)
  → Si action = "send":
      → BehaviorEngine.deliver() directamente
      → Notificación a la dueña (opcional, si alguna dimensión está cerca del umbral)
      → Learning post-turno (registra traza, Staging si corrección posterior)
  → Si action = "approve":
      → Flujo supervisado normal (como en Fase 1/2)
```

6.2 Recontacto por silencio (job programado)

```
Job programado (ej. cada hora):
  → Busca VIPs con last_contact_at < now() - inactivity_days
    Y sin recontacto pendiente
  → RecontactService.execute_recontact(vip_id)
      → Director (pipeline reducido):
          - Recupera memory y policy (stubs si no hay)
          - Genera mensaje con plantilla + personalización
          - Evaluador (umbrales laxos)
          - Decisor:
              - Si autónomo → send
              - Si no → approve
      → Si send → BehaviorEngine.deliver()
      → Si approve → cola de aprobación de la dueña
  → Programar próximo recontacto (según configuración)
```

6.3 Promo no-VIP (trigger exacto)

```
business_message de no-VIP (no está en allowlist)
  → Middleware de auth detecta no-VIP
  → PromoService.match_trigger(texto)
  → Si match:
      → PromoService.execute_promo(chat_id, trigger)
          → BehaviorEngine.deliver_with_sequence(sequence, ctx)
      → No se guarda en pipeline_traces
  → Si no match:
      → Ignorar (no se responde)
```

6.4 Calibración automática (job semanal)

```
Job programado (ej. cada domingo a las 3 AM):
  → Si FEATURE_CALIBRATION_ENABLED:
      → CalibrationService.calibrate_thresholds(window_days=30)
      → Actualiza system_config con nuevos umbrales
      → Registra en learning_metrics la tasa de aprobación y drift
      → Notifica a la dueña con resumen: "Umbrales actualizados: [nuevos valores]"
```

6.5 Mensajes divididos (Behavior avanzado)

```
Cuando se envía un mensaje largo:
  → BehaviorEngine.deliver() verifica ctx.allow_split
  → Si True y len(texto) > split_chars:
      → Divide el texto en segmentos
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

[📥 Exportar datos] [🔙 Volver]
```

---

8. Integración con Fases Anteriores

Fase Cambios necesarios en Fase 3
Fase 1 El Director y el Decisor se extienden para manejar send y el nuevo orden de prioridades. El Behavior Engine se actualiza con nuevas capacidades (split, quirks).
Fase 2 El GrayZoneService y StagingService se mantienen. La zona gris ahora puede activarse también en modo autónomo (si el Decisor decide consult_doctrine en lugar de send). La calibración usa datos de corrección de Staging.
Trazabilidad Las métricas y la calibración usan los datos de pipeline_traces; se añaden campos de timings y corrección. El dashboard muestra las métricas.

Compatibilidad: Todos los nuevos comportamientos están envueltos en feature flags, por lo que la Fase 3 puede activarse gradualmente sin romper Fase 2.

---

9. Roadmap de Implementación

Hito Descripción Dependencias
H3.1 Extender el Decisor con reglas de modo autónomo y umbrales. Feature flag FEATURE_AUTONOMOUS_MODE.
H3.2 Implementar AutonomousModeService y notificaciones opcionales. H3.1
H3.3 Implementar RecontactService y job programado. Tabla recontact_schedules.
H3.4 Implementar PromoService y tabla promo_triggers. —
H3.5 Implementar CalibrationService con algoritmo de ajuste de umbrales. Tabla learning_metrics.
H3.6 Extender BehaviorEngine con mensajes divididos y quirks humanos. Feature flag FEATURE_ADVANCED_BEHAVIOR.
H3.7 Implementar job semanal de cálculo de métricas y drift. H3.5
H3.8 Añadir comandos de admin para ver métricas y configurar promos/recontactos. H3.3, H3.4, H3.7
H3.9 Pruebas de integración y activación gradual de flags. Todos los anteriores

Criterio de salida: El sistema puede operar en modo autónomo (con fallback a supervisado), recontactar VIPs inactivos, responder promocionalmente a no-VIP, ajustar sus propios umbrales basado en datos, y mostrar métricas de aprendizaje en el DM.

---

10. Trazabilidad REQ → Componentes de Fase 3

Bloque REQ Componente(s)
REQ-MODE-02, 07, 08, 09 AutonomousModeService, Decisor, notificaciones
REQ-REE-01..04 RecontactService, job programado, pipeline reducido
REQ-PRO-01..04 PromoService, trigger exacto, BehaviorEngine
REQ-EVAL-02..04 CalibrationService, ajuste de umbrales
REQ-MET-01..04 LearningMetrics, drift detection, dashboard
REQ-HUM-04..06 BehaviorEngine avanzado (split, quirks)

---

11. Decisiones de Diseño Abiertas

1. Umbrales iniciales para modo autónomo: ¿Qué valores usar al arrancar (antes de la primera calibración)? Se sugiere conservador: seguridad >= 0.9, doctrina >= 0.8, naturalidad >= 0.7. Se ajustarán automáticamente tras 50 turnos.
2. Frecuencia de calibración: ¿Cada semana? ¿Cada 100 turnos? Se recomienda semanal con ventana de 30 días.
3. Recontacto: ¿Incluir solo a VIPs con los que ha habido interacción reciente (últimos 30 días) o a todos? Se sugiere aplicar a todos los activos.
4. Promo no-VIP: ¿Secuencia fija o parámetros variables (ej. nombre del producto)? Por simplicidad, se deja fija en V1.
5. Drift de estilo: ¿Umbral de alerta? 0.1 en distancia coseno parece razonable.
6. Mensajes divididos: ¿Longitud máxima por mensaje? El límite de Telegram es 4096 caracteres, pero se puede dividir antes (ej. 2000 caracteres) para que sea más natural.

---

12. Relación con Anexos y Documentos

Documento Relación
SPEC.md v1.5 El Director y el Behavior Engine se extienden; el Decisor añade nuevas reglas.
SPEC-FASE2.md La zona gris y staging se integran con el modo autónomo; la calibración usa datos de corrección.
Anexo T (Trazabilidad) Las métricas y la calibración usan pipeline_traces.
Anexos_contratos.md El Decisor (Anexo F) se actualiza; Behavior Engine (Anexo I) se extiende.

---

13. Notas Finales

· Gradualidad: Esta fase es la más compleja. Se recomienda activar los flags uno a uno: primero Recontacto (menos riesgoso), luego Promo, luego Modo Autónomo (después de calibración), y finalmente Behavior avanzado.
· Monitoreo: La dueña debe recibir notificaciones semanales con métricas para tener visibilidad del rendimiento.
· Rollback: Todos los nuevos comportamientos tienen feature flags; se puede desactivar cualquier funcionalidad sin redeploy.

---

Fin del SPEC-FASE3.md
Última actualización: Julio 2026
Equipo de Arquitectura — Producto completo listo para desarrollo.

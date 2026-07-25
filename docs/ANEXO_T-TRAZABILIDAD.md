
Anexo T — Sistema de Trazabilidad Interactiva (Auditoría de Turnos)

Diana Business Bot / Sistema de Automatización de Chats VIP

Campo Valor
Nivel Diseño e implementación del sistema de trazabilidad para el DM de la dueña
Basado en SPEC.md v1.5 y SPEC-FASE2.md v2.1
Audiencia Ingeniería
Versión 1.0
Estado Pendiente de implementación (puede ejecutarse en paralelo a Fase 2)

---

1. Propósito

Permitir que la dueña (o el equipo de operaciones) pueda inspeccionar el paso a paso de cualquier turno, desde la recepción del mensaje hasta la decisión final y entrega.

Objetivos concretos:

1. Ver el resumen de turnos recientes (últimos N) con su estado y decisión.
2. Explorar la traza completa de un turno específico: entrada/salida de cada nodo cognitivo, tiempos de ejecución, y errores.
3. Navegar entre los pasos del pipeline de forma interactiva desde el DM.
4. Exportar la traza en formato JSON para depuración o reportes.
5. No añadir complejidad al pipeline existente; toda la información ya se persiste, solo se expone.

---

2. Alcance

2.1 Dentro de alcance

ID Área
T-01 Extender pipeline_traces con un campo timings (JSON) que registre la duración de cada nodo.
T-02 Modificar el CognitiveDirector para que registre los tiempos de cada paso (Analista, Retrievers, Generador, Evaluador, Decisor).
T-03 Implementar AdminService.get_recent_turns(limit=10) para listar turnos con información resumida.
T-04 Implementar AdminService.get_full_trace(turn_id) para recuperar todos los objetos intermedios de un turno.
T-05 Añadir comandos /turnos y /traza <turn_id> en el handler de admin.
T-06 Diseñar mensajes con botones inline para paginación, navegación y visualización de detalles de cada paso.
T-07 Añadir botón "Ver traza" en el mensaje de aprobación (cuando la dueña recibe un borrador para aprobar).
T-08 (Opcional) Añadir exportación a JSON desde la vista de traza.

2.2 Fuera de alcance

ID Exclusión
T-O1 Herramienta de análisis avanzado (gráficas, estadísticas agregadas).
T-O2 Acceso a trazas desde fuera del DM de la dueña (no hay interfaz web en V1).
T-O3 Modificación de trazas (son solo lectura).

---

3. Modelo de Datos (Extensión)

3.1 Extensión de pipeline_traces

Añadir un nuevo campo timings en la tabla existente. Si se usa SQLAlchemy, añadir una columna JSONB:

```sql
ALTER TABLE pipeline_traces ADD COLUMN timings JSONB DEFAULT '{}'::jsonb;
```

Estructura del objeto timings (ejemplo):

```json
{
  "analyst_ms": 120.5,
  "planner_ms": 0.3,
  "memory_retriever_ms": 80.2,
  "policy_retriever_ms": 15.1,
  "examples_retriever_ms": 20.4,
  "context_builder_ms": 2.1,
  "generator_ms": 850.3,
  "evaluator_ms": 220.6,
  "decider_ms": 0.4,
  "total_ms": 1309.9
}
```

Campos opcionales: si algún paso no se ejecutó (ej. un retriever stub) o falló, se puede registrar null o un valor indicativo.

3.2 Consultas indexadas

Para que la lista de turnos recientes sea rápida, añadir índice:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS pipeline_traces_created_at_idx ON pipeline_traces (created_at DESC);
```

---

4. Nuevos Servicios

4.1 AdminTraceService

Este servicio expone métodos para recuperar y formatear trazas. Está ubicado en application/admin_trace_service.py.

```python
from typing import List, Optional
from uuid import UUID
from datetime import datetime

class TurnSummary:
    turn_id: UUID
    chat_id: int
    vip_name: Optional[str]
    message_preview: str   # primeros 50 caracteres del mensaje original
    decision: str          # "approve", "escalate", "consult_doctrine", etc.
    status: str            # "delivered", "escalated", "pending_approval", etc.
    created_at: datetime
    correction_applied: bool

class FullTrace:
    turn_id: UUID
    chat_id: int
    vip_id: UUID
    created_at: datetime
    comprehension: dict
    plan: dict
    retrieved: dict       # mapeo capacidad → resultado
    prompt_text: str
    generated_text: str
    evaluation: dict
    decision: dict
    delivery_result: dict
    timings: dict
    error: Optional[str]

class AdminTraceService:
    async def get_recent_turns(limit: int = 10, offset: int = 0) -> List[TurnSummary]:
        """Recupera los últimos N turnos con resumen."""
        ...
    
    async def get_full_trace(turn_id: UUID) -> Optional[FullTrace]:
        """Recupera la traza completa de un turno específico."""
        ...
    
    async def get_traces_by_chat(chat_id: int, limit: int = 5) -> List[TurnSummary]:
        """Recupera los últimos turnos de un VIP específico (útil para depuración)."""
        ...
```

4.2 TraceTimingMiddleware (opcional)

Para no ensuciar el Director con lógica de medición, se puede implementar un context manager o decorador que envuelva cada paso.

```python
class TimingContext:
    def __enter__(self): ...
    def __exit__(self, *args): ...

# Uso en el Director:
with TimingContext("analyst") as timer:
    comprehension = await self.analyst.analyze(...)
timings["analyst_ms"] = timer.elapsed_ms
```

---

5. Interfaz en el DM (Flujos de Interacción)

5.1 Comando /turnos

Flujo:

1. Dueña escribe /turnos en el DM del bot.
2. El bot responde con un mensaje que lista los últimos 10 turnos (ordenados por created_at DESC).
3. Cada turno se muestra con:
   · ID (abreviado, ej. abc123).
   · Nombre del VIP (si existe).
   · Previsualización del mensaje original (primeros 50 caracteres).
   · Decisión y estado.
   · Fecha/hora.
   · Botón "Ver traza" que dispara /traza <turn_id>.
4. Paginación: botones "◀ Anterior" y "Siguiente ▶" para navegar por páginas de 10 turnos.

Ejemplo de mensaje:

```
📋 Últimos turnos (página 1/3):

1. [abc123] Ana (chat 123): "¿Cuánto cuesta el paquete premium?" → Aprobado (hoy 14:32)
2. [def456] Luis (chat 456): "¿Tienes disponibilidad para..." → Aprobado (hoy 12:15)
3. [ghi789] María (chat 789): "Quiero cancelar mi suscripción" → Escalado (ayer 18:00)
...

Botones: [◀ Anterior] [Siguiente ▶] [Ver traza abc123] [Ver traza def456] [Ver traza ghi789]
```

5.2 Comando /traza <turn_id>

Flujo:

1. Dueña escribe /traza abc123 o hace clic en el botón "Ver traza".
2. El bot responde con un mensaje resumen de la traza:
   · Mensaje original del VIP.
   · Borrador generado.
   · Decisión final y estado.
   · Tiempo total.
3. Debajo, una lista de los pasos ejecutados (Analista, Planificador, etc.) con:
   · Nombre del paso.
   · Duración en ms.
   · Estado (OK, Error, o Saltado).
   · Botón "Ver detalles" para cada paso.
4. Al hacer clic en "Ver detalles" de un paso, el bot envía un mensaje aparte con:
   · Entrada (el input que recibió ese nodo).
   · Salida (el output que produjo).
   · Si hubo error, el mensaje de error.
   · Botón "Volver" para regresar al resumen de la traza.

Ejemplo de mensaje resumen:

```
🔍 Traza del turno abc123
📅 25/07/2026 14:32:15
👤 VIP: Ana
💬 Mensaje original: "¿Cuánto cuesta el paquete premium?"
✍️ Borrador generado: "Hola Ana, el paquete premium tiene un costo de $XXX. ¿Te ayudo con algo más?"
✅ Decisión: Aprobar (modo supervisado)
⏱️ Tiempo total: 1307ms

Pasos:
1. Analista (120ms) → Ver detalles
2. Planificador (0.5ms) → Ver detalles
3. MemoryRetriever (80ms) → Ver detalles
4. PolicyRetriever (15ms) → Ver detalles
5. ExamplesRetriever (20ms) → Ver detalles
6. ContextBuilder (2ms) → Ver detalles
7. Generador (850ms) → Ver detalles
8. Evaluador (220ms) → Ver detalles
9. Decisor (0.4ms) → Ver detalles

[📥 Exportar JSON] [🔙 Volver a turnos]
```

Ejemplo de detalle de un paso (mensaje separado):

```
🔍 Detalle del paso: Analista
⏱️ Duración: 120ms
✅ Estado: OK

📥 Entrada:
{
  "turno_actual": "¿Cuánto cuesta el paquete premium?",
  "historial_reciente": [...]
}

📤 Salida:
{
  "intent": "pedir_precio",
  "topics": ["precio", "paquete_premium"],
  "emotion": "neutral",
  "urgency": "media",
  "risk": "medio",
  "needs_memory": true,
  "needs_policy": true,
  ...
}

[🔙 Volver a la traza]
```

5.3 Botón "Ver traza" en el mensaje de aprobación

Cuando la dueña recibe un borrador para aprobar (en modo supervisado), el mensaje incluirá un botón adicional:

```
📝 Borrador para aprobar:
"Hola Ana, el paquete premium..."

[✅ Aprobar] [✏️ Corregir] [🔄 Regenerar] [🔍 Ver traza]
```

Al hacer clic en "Ver traza", se muestra el resumen de la traza de ese turno (igual que /traza).

---

6. Consideraciones de Seguridad y Privacidad

· Autenticación: Todos los comandos y botones deben validar que el usuario sea el admin configurado (REQ-AUTH-08).
· Datos sensibles: Las trazas contienen el contenido completo de las conversaciones (mensajes del VIP, borradores, prompts). Solo el admin tiene acceso.
· TTL: Las trazas se conservan según la política de retención configurada (por defecto 30 días, REQ-PER-06). El comando /turnos solo muestra las que no han expirado.
· Exposición: No se muestran IDs internos de la base de datos (UUIDs completos) en los mensajes; se usan abreviaturas o hashes cortos para evitar exposición innecesaria.

---

7. Roadmap de Implementación

Hito Descripción Dependencias
H1 Extender tabla pipeline_traces con campo timings (migración). Ninguna
H2 Implementar TimingContext o decorador en el Director para registrar tiempos en cada paso. H1
H3 Implementar AdminTraceService con métodos get_recent_turns y get_full_trace. H2
H4 Añadir comando /turnos en el handler de admin. H3
H5 Añadir comando /traza <turn_id> en el handler de admin. H3
H6 Implementar paginación y navegación con botones inline para la lista de turnos. H4
H7 Implementar la vista de detalle de cada paso (mensaje separado con entrada/salida). H5
H8 Añadir botón "Ver traza" en el mensaje de aprobación (callback). H5
H9 (Opcional) Implementar exportación a JSON desde la vista de traza. H5

Criterio de salida: La dueña puede, desde su DM, ver los últimos turnos, seleccionar uno y explorar el detalle de cada nodo del pipeline, incluyendo tiempos de ejecución y la entrada/salida de cada paso.

---

8. Relación con otros Documentos

Documento Relación
SPEC.md v1.5 La tabla pipeline_traces ya está definida; este anexo extiende su uso.
SPEC-FASE2.md La trazabilidad es especialmente útil para depurar el flujo de zona gris y staging; se recomienda implementarla en paralelo.
AGENTS.md Los agentes deben saber que no se pueden eliminar registros de pipeline_traces manualmente; la limpieza es por TTL configurable.

---

9. Consideraciones de Rendimiento

· Volumen: El sistema maneja decenas de VIPs y quizás cientos de turnos por día. La tabla pipeline_traces puede crecer, pero con TTL configurable (ej. 30 días) se mantiene acotada.
· Consultas: get_recent_turns debe usar el índice created_at para ser rápida. get_full_trace es una búsqueda por clave primaria.
· Caché: No se necesita caché en V1; las consultas son livianas y de baja frecuencia.

---

10. Notas Finales

· No intrusivo: Este anexo no modifica el pipeline cognitivo ni el comportamiento del bot. Solo añade visibilidad.
· Iterativo: En versiones futuras, se podría añadir búsqueda por VIP, filtro por decisión, o gráficas de tiempos.
· Depuración remota: Con esta herramienta, el equipo de soporte (si la dueña lo permite) podría revisar trazas de forma remota, simplificando la resolución de incidencias.

---

Fin del Anexo T — Sistema de Trazabilidad Interactiva
Última actualización: Julio 2026
Equipo de Arquitectura — Listo para implementación.

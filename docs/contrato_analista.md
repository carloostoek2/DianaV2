## Anexo A — Contrato detallado del Analista

### A.1 Responsabilidad exacta

El Analista responde **una sola pregunta**: *"¿qué está pasando en este turno?"*. No responde "¿qué hago?" (eso es el Planificador + Decisor) ni "¿qué digo?" (eso es el Generador). Cualquier prompt de Analista que contenga instrucciones de tono, de redacción o de política de negocio está mal diseñado — esas reglas no le corresponden (REQ-NFR-13, especialización estricta).

### A.2 Entrada

```
AnalistaInput {
  turno_actual: string                # texto del mensaje que disparó el turno
  historial_reciente: Array<{         # ventana corta, NO el historial completo
    autor: "vip" | "dueña",
    texto: string,
    timestamp: datetime
  }>                                   # tamaño configurable; recomendado 5-10 mensajes,
                                        # suficiente para desambiguar referencias ("¿y eso
                                        # cuánto cuesta?") sin cargar contexto de negocio real
}
```

Explícitamente **no** recibe: memoria del VIP, políticas, ejemplos de estilo, ni el borrador de ningún turno anterior. Si el Analista necesitara eso para clasificar, sería una señal de que se le está pidiendo hacer el trabajo del Generador — se revisa en diseño, no se resuelve dándole más contexto.

### A.3 Salida — schema completo (JSON Schema, agnóstico de proveedor)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "intent", "topics", "emotion", "urgency", "risk",
    "needs_memory", "needs_policy", "needs_schedule",
    "needs_examples", "needs_history", "needs_context"
  ],
  "properties": {
    "intent": {
      "type": "string",
      "description": "Verbo + objeto en minúsculas, sin puntuación. Ej: 'pedir_precio', 'agendar_encuentro', 'quejarse_demora', 'saludar', 'despedirse'. No es una lista cerrada — el Analista puede acuñar una etiqueta nueva si ninguna existente aplica; la lista de intents observados se revisa periódicamente por la dueña/admin fuera de este pipeline."
    },
    "topics": {
      "type": "array",
      "items": { "type": "string" },
      "description": "0 a N temas mencionados, en minúsculas. Puede estar vacío si el mensaje es puro saludo/despedida."
    },
    "emotion": {
      "type": "string",
      "enum": ["neutral", "positiva", "ansiosa", "molesta", "triste", "cariñosa", "urgente"],
      "description": "Enum cerrado deliberadamente (a diferencia de intent/topics) porque el Decisor y el Constructor de Contexto ramifican sobre este campo; una etiqueta libre rompería esas reglas."
    },
    "urgency": { "type": "string", "enum": ["baja", "media", "alta"] },
    "risk": {
      "type": "string",
      "enum": ["bajo", "medio", "alto"],
      "description": "Riesgo de que la respuesta requiera juicio humano fino (temas sensibles, ambigüedad emocional alta, posible malentendido). NO es lo mismo que 'urgency'. Alimenta el umbral de escalación del Decisor (§3.11), junto con 'seguridad' del Evaluador — son dos señales independientes, una del Analista (a priori, antes de generar) y otra del Evaluador (a posteriori, sobre el borrador ya escrito)."
    },
    "needs_memory":   { "type": "boolean", "description": "¿Este turno se beneficia de saber algo dicho en conversaciones anteriores no presentes en historial_reciente?" },
    "needs_policy":   { "type": "boolean", "description": "¿Este turno toca una zona donde existe o podría existir una regla de negocio explícita (precios, límites, qué se ofrece o no)?" },
    "needs_schedule": { "type": "boolean", "description": "¿Este turno requiere saber disponibilidad/agenda real de la dueña?" },
    "needs_examples": { "type": "boolean", "description": "¿Ayuda ver cómo la dueña respondió antes a un mensaje de este mismo tipo?" },
    "needs_history":  { "type": "boolean", "description": "Casi siempre true; false solo en saludos/mensajes triviales sin referencia a nada previo." },
    "needs_context":  { "type": "boolean", "description": "¿Hay estado temporal relevante (lleva esperando, es la primera vez que escribe hoy, etc.)?" }
  }
}
```

### A.4 Ejemplos (few-shot de referencia — no van al prompt de producción tal cual, sirven para calibrar el prompt real)

**Ejemplo 1 — trivial**
- `turno_actual`: "Buenas noches 😊"
- Salida esperada:
```json
{
  "intent": "saludar",
  "topics": [],
  "emotion": "cariñosa",
  "urgency": "baja",
  "risk": "bajo",
  "needs_memory": false,
  "needs_policy": false,
  "needs_schedule": false,
  "needs_examples": false,
  "needs_history": false,
  "needs_context": false
}
```

**Ejemplo 2 — requiere política**
- `turno_actual`: "¿Y si quiero algo más personalizado, eso tiene costo aparte?"
- Salida esperada:
```json
{
  "intent": "pedir_precio",
  "topics": ["personalización", "precio"],
  "emotion": "neutral",
  "urgency": "media",
  "risk": "medio",
  "needs_memory": false,
  "needs_policy": true,
  "needs_schedule": false,
  "needs_examples": true,
  "needs_history": true,
  "needs_context": false
}
```
`risk: medio` porque toca precios (zona donde una respuesta mal calibrada tiene costo real), aunque la emoción sea neutral.

**Ejemplo 3 — alto riesgo, dispara cortocircuito antes de llegar aquí**
- `turno_actual`: contiene un tema de la lista de exclusión determinista del Director (§3.3, Paso 0).
- El Analista **nunca ve este mensaje** — el cortocircuito actúa antes. Se documenta aquí solo para dejar claro el límite: el Analista no es la primera línea de seguridad, es la segunda.

**Ejemplo 4 — ambigüedad emocional**
- `turno_actual`: "jaja ok como digas" (después de que la dueña —vía el sistema— dijo que no podía verla esta semana)
- Salida esperada (usando `historial_reciente` para desambiguar):
```json
{
  "intent": "responder_reprogramacion",
  "topics": ["disponibilidad"],
  "emotion": "molesta",
  "urgency": "media",
  "risk": "medio",
  "needs_memory": true,
  "needs_policy": false,
  "needs_schedule": true,
  "needs_examples": true,
  "needs_history": true,
  "needs_context": true
}
```
El texto literal es neutro/informal ("jaja ok"), pero el patrón "respuesta corta + jaja después de una negativa" es una señal de emoción contenida — por eso el Analista necesita `historial_reciente`, no solo el mensaje suelto. Este es el caso que justifica que la ventana de historial no sea cero.

### A.5 Definición de "tool"/function-calling (agnóstica de proveedor)

Si el proveedor LLM soporta structured output / tool use nativo, se recomienda declarar el schema de A.3 como definición de función y **forzar** su uso (no dejar la salida como texto libre a parsear). Forma agnóstica:

```json
{
  "name": "registrar_comprension",
  "description": "Registra la clasificación estructurada del turno actual. Debe llamarse exactamente una vez por turno.",
  "parameters": { "$ref": "#/A.3" }
}
```

Si el proveedor no soporta tool-calling forzado, alternativa: pedir salida JSON pura con instrucción explícita de "responde únicamente con el JSON, sin texto adicional ni bloque de código", y aplicar el parseo + validación de A.6 igual.

### A.6 Validación y manejo de errores

1. **Validación de schema** (tipo, enum, campos requeridos) inmediatamente después de recibir la respuesta del LLM, antes de que el Director avance al Planificador.
2. Si falla la validación:
   - Reintento único con el mismo input (los LLM son no-determinísticos; a veces el segundo intento es válido).
   - Si el segundo intento también falla → `Turn.status = failed`, se registra el motivo (`"analista_schema_invalido"`) y se notifica a la dueña (REQ-VIP-08). **No se envía nada al VIP.**
3. **No hay "Comprensión parcial".** Un objeto con 10 de 11 campos válidos se trata como inválido completo — el Constructor de Contexto (§3.8) depende de que todos los `needs_*` existan para poder pedir exactamente lo necesario; una Comprensión a medias podría subestimar silenciosamente lo que se necesita saber (riesgo peor que fallar el turno completo).
4. **Timeout**: si el proveedor LLM no responde dentro del límite configurado, se trata igual que un fallo de schema (mismo camino de reintento único → `failed`), no como ausencia de riesgo.

### A.7 Invariantes que no debe romper ninguna implementación futura

- El Analista nunca recibe el `Borrador` de su propio turno (no existe todavía en este punto del pipeline) ni el de turnos anteriores.
- El Analista nunca escribe a `VipContact`, `Chat` ni ninguna entidad de negocio — es de solo lectura sobre `historial_reciente`.
- Cambiar el enum de `emotion` o `risk` es un cambio de contrato que rompe al Decisor y al Constructor de Contexto — requiere versionar el schema (`comprension_schema_version`) y actualizar ambos consumidores en el mismo cambio, no solo el Analista.

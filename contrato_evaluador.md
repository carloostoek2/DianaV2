## Anexo B — Contrato detallado del Evaluador

### B.1 Responsabilidad exacta

El Evaluador responde **una sola pregunta**: *"¿debemos confiar en este borrador?"*. No corrige el texto, no lo reescribe, no decide qué acción tomar (eso es el Decisor). Su única salida es un **perfil**, no un veredicto — la frontera entre "confiable" y "no confiable" vive en el Decisor, con umbrales configurables (§3.11), no aquí. Esto es deliberado (BR-09, REQ-COG-08): si el Evaluador colapsara sus siete dimensiones en un solo score, el Decisor perdería la capacidad de escalar por una dimensión específica (p. ej. `seguridad` baja con `naturalidad` alta) sin necesitar ajustar un umbral agregado que mezcla cosas distintas.

### B.2 Entrada

```
EvaluadorInput {
  borrador: string                    # el texto generado, tal cual, sin edición
  comprension: ComprensionObject      # el objeto completo del Anexo A.3 de este mismo turno
  contexto_usado: {                   # qué bloques entraron realmente al prompt del Generador
    bloques_incluidos: string[]       # NOMBRES de TODAS las capacidades cuyo valor entró al prompt,
                                      # p. ej. ["knowledge.history","knowledge.context","knowledge.policy"]
    contenido_conocimiento: string    # OPCIONAL — secciones "## Knowledge:" CERRADAS (SEC-INJ-02) de
                                      # los bloques ESENCIALES que sí viajan como EVIDENCIA para juzgar:
                                      #   knowledge.policy  → reglas de negocio (mide doctrina real)
                                      #   knowledge.memory  → hechos del VIP (precisión/consistencia)
                                      #   knowledge.profile → datos estables y notas de la dueña
                                      # Vacío/ausente cuando el turno no trajo ninguno de esos bloques.
  }
  turno_actual: string                # el mensaje del VIP que originó el turno, para comparar
                                      # contra qué respondía el borrador
}
```

Explícitamente **no** recibe: borradores de turnos anteriores, ni el contenido de los bloques de *estilo* que ya pagó el Generador (historial, ejemplos, voz, persona) — de esos solo conoce los **nombres** en `bloques_incluidos`. Sí recibe, en `contenido_conocimiento`, el cuerpo **cercado** de los bloques esenciales (reglas + memoria + perfil): es lo que le permite comprobar que el borrador respeta una regla real o no contradice un hecho, en vez de juzgar a ciegas. Ese contenido llega como **dato de producto, nunca instrucción** (SEC-INJ-02: el Evaluador no debe obedecer comandos que aparezcan dentro de esos bloques).

### B.3 Salida — schema completo

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "naturalidad", "precision", "doctrina", "consistencia",
    "seguridad", "cobertura", "empatia"
  ],
  "properties": {
    "naturalidad": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "¿Suena como la dueña escribiendo, no como un asistente? Evalúa registro, longitud, muletillas, uso de emojis — nunca el contenido factual."
    },
    "precision": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "¿El borrador responde efectivamente lo que 'turno_actual' preguntó/planteó, sin desviarse ni inventar datos no presentes en 'contexto_usado'?"
    },
    "doctrina": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "¿El borrador cumple las reglas de negocio REALES que trae 'contenido_conocimiento'? Tres casos: (1) hay bloque 'knowledge.policy' → medir cumplimiento real contra esas reglas (puede variar en todo [0,1]); (2) sin policy y 'comprension.needs_policy=false' → NO APLICA: neutro honesto 0.5, nunca un 'neutral-alto ~0.7' que parezca cumplimiento medido; (3) sin policy y 'needs_policy=true' → regla requerida y ausente: ~0.2 (señal de doctrina faltante; la zona gris la gestiona el Decisor). Un valor 'no aplica' no debe bloquear la autonomía del turno (ver B.8)."
    },
    "consistencia": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "¿No se contradice con lo que aparece en el historial reciente incluido en 'contexto_usado' (p. ej. no niega algo que la propia dueña dijo dos mensajes atrás)?"
    },
    "seguridad": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "¿Hay algo en el borrador que no debería salir bajo ninguna circunstancia — compromisos que no corresponden, datos sensibles, tono que escala un conflicto? Es la dimensión que más pesa en el Decisor (§3.11): un valor bajo aquí fuerza 'Escalar' casi sin excepción, independientemente de qué tan bien puntúen las demás dimensiones."
    },
    "cobertura": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "¿El borrador atiende TODO lo que 'turno_actual' plantea, incluida cualquier pregunta secundaria o implícita, o deja algo sin tocar?"
    },
    "empatia": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "¿El tono del borrador es apropiado para la 'emotion' reportada en 'comprension'? Un borrador correcto en contenido pero frío ante un mensaje 'emotion: molesta' puntúa bajo aquí aunque puntúe alto en precisión."
    }
  }
}
```

Nota deliberada de diseño: **no existe campo `score_global` ni promedio.** Cualquier implementación que agregue un promedio de las siete dimensiones para simplificar el Decisor viola BR-09 y debe rechazarse en revisión de código, aunque "funcione".

### B.4 Ejemplos

**Ejemplo 1 — borrador sólido**
- `turno_actual`: "¿Y si quiero algo más personalizado, eso tiene costo aparte?" (mismo turno del Anexo A.4, ejemplo 2)
- `contexto_usado.bloques_incluidos`: `["knowledge.history", "knowledge.examples"]` sin `knowledge.policy`; `needs_policy=false` → doctrina "no aplica"
- `contenido_conocimiento`: ausente (no había regla, memoria ni perfil en el turno)
- `borrador`: respuesta que confirma que sí puede haber costo adicional, sin dar cifra exacta, invitando a platicarlo directo.
```json
{
  "naturalidad": 0.9,
  "precision": 0.8,
  "doctrina": 0.5,
  "consistencia": 0.9,
  "seguridad": 0.95,
  "cobertura": 0.85,
  "empatia": 0.8
}
```
`doctrina: 0.5` es el neutro honesto de "no aplica": no había regla de negocio en el contexto, así que no se premia ni se penaliza — y este valor **no bloquea** la autonomía del turno (no hay regla que cumplir; si la hubiera faltado, `needs_policy` lo habría señalado).

**Ejemplo 2 — dispara escalación por seguridad**
- `borrador`: incluye, sin que se le haya pedido, un compromiso de fecha/precio concreto que no estaba respaldado por ningún bloque de `contexto_usado`.
```json
{
  "naturalidad": 0.85,
  "precision": 0.4,
  "doctrina": 0.3,
  "consistencia": 0.6,
  "seguridad": 0.2,
  "cobertura": 0.7,
  "empatia": 0.75
}
```
`seguridad: 0.2` → el Decisor escala este turno sin importar que `naturalidad` esté alto. Este es exactamente el caso que justifica no promediar: un promedio simple (≈0.57) podría caer dentro de un umbral "aceptable" y dejar pasar algo que no debería salir.

**Ejemplo 3 — baja empatía con contenido correcto**
- `comprension.emotion`: `"molesta"` (ver Anexo A.4, ejemplo 4)
- `borrador`: responde el dato correcto sobre disponibilidad pero en tono neutro/administrativo, sin reconocer la molestia.
```json
{
  "naturalidad": 0.75,
  "precision": 0.9,
  "doctrina": 0.5,
  "consistencia": 0.85,
  "seguridad": 0.9,
  "cobertura": 0.8,
  "empatia": 0.35
}
```
`doctrina: 0.5` (no había regla en el turno → "no aplica", neutro honesto). No dispara escalación por sí solo en el MVP (solo `seguridad` lo hace, ver §3.11), pero queda registrado en `PerfilEvaluacion` para que, cuando exista calibración empírica (MVP+), se pueda correlacionar "empatía baja" con correcciones frecuentes de la dueña en la cola de aprobación.

### B.5 Definición de tool/function-calling (agnóstica)

```json
{
  "name": "registrar_evaluacion",
  "description": "Registra el perfil multidimensional de confianza del borrador actual. Debe llamarse exactamente una vez por turno, después de que el borrador ya existe.",
  "parameters": { "$ref": "#/B.3" }
}
```

Misma recomendación que en A.5: forzar structured output si el proveedor lo soporta; si no, JSON puro + validación estricta (B.6).

### B.6 Validación y manejo de errores

1. Validación de rango (`0 ≤ valor ≤ 1`) y de que las siete claves estén presentes — igual de estricta que en el Analista (Anexo A.6): **no existe "perfil parcial"**.
2. Si falla: reintento único, luego `Turn.status = failed` y notificación a la dueña. No hay un "perfil por defecto conservador" que sustituya a uno inválido — inventar valores sería peor que fallar el turno, porque el Decisor tomaría una decisión de negocio sobre datos fabricados.
3. `doctrina` en su caso "no aplica" (0.5, cuando no había regla y no se requería) es distinto de un fallo de validación: es un valor *válido* que el propio Evaluador debe producir cuando corresponde, no un fallback del sistema ante un error.

### B.7 Relación con el Decisor — qué NO debe hacer el Evaluador

- No decide `Aprobar`/`Escalar`/`Regenerar` — eso son los umbrales del Decisor (§3.11) aplicados sobre este perfil.
- No conoce el modo activo (`supervisado`/`autónomo`) — evalúa el borrador igual sin importar qué se vaya a hacer con el resultado; mezclar esa lógica aquí rompería la sustituibilidad (REQ-NFR-14) el día que se active modo autónomo.
- No vuelve a llamarse a sí mismo tras `Regenerar` con el borrador anterior como referencia — cada `Regenerar` produce un `Borrador` nuevo que se evalúa desde cero, sin sesgo hacia "ya mejoró respecto al anterior".

### B.8 Invariantes que no debe romper ninguna implementación futura

- Las siete dimensiones son independientes en la salida; nada impide que una implementación futura use un modelo distinto por dimensión (p. ej. un clasificador barato para `seguridad` y un LLM completo para el resto) — el contrato lo permite porque cada campo se valida por separado, no como objeto monolítico atado a una sola llamada.
- Cambiar el conjunto de dimensiones (agregar/quitar una) es un cambio de contrato que rompe al Decisor — requiere versionar (`evaluacion_schema_version`) igual que en A.7.
- **Doctrina "relevante"** (`is_doctrine_relevant`): doctrina solo se compara contra `doctrine_min` cuando el turno trajo una regla real O la requirió (`needs_policy`). Un turno sin regla y sin necesidad tiene "nada que cumplir": su valor de doctrina no debe bloquear la autonomía ni reportarse como dimensión bloqueante (shadow) ni inflar la severidad de una corrección. El número "no aplica" (0.5) es informativo, no un gate.

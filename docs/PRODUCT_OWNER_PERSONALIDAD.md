# Product Owner — Personalidad y reglas (panel de Telegram)

**Status:** **IMPLEMENTED** (pool `persona-admin` closed 2026-08-04; ampliado por el pool
`persona-reglas`, 2026-10-02)
**Project:** DianaV2
**Source:** owner conversation + decisiones de la dueña (guardado en base con historial;
todo desde el inicio; aplica sin reiniciar)
**Audience:** dueña del producto + implementadores
**Pool evidence:** `.planning/quick/persona-admin/`, `.planning/hardener/persona-reglas/`

Feature flag: `FEATURE_PERSONA_ADMIN_ENABLED` / `feature_persona_admin_enabled`
(default **false** — se activa en la config del servidor, igual que sandbox/staging).

---

## Qué hace

Desde **/menu → 🎭 Personalidad y reglas**, la dueña revisa y edita cómo habla Diana:

| Sección | Qué se puede hacer |
|---------|--------------------|
| 📝 Cómo habla Diana | Ver y editar la descripción base (el "prompt base") |
| ✍️ Reglas de tono y estilo | Listar, agregar, editar y eliminar reglas (ej: "Máximo 2-3 líneas por mensaje") |
| 👤 Datos personales | Agregar/editar/eliminar datos (formato `id \| tema1, tema2 \| hecho`) |
| 🗣️ Patrones de voz | Ídem (formato `id \| tag1, tag2 \| patron \| uso`) |
| 📜 Políticas de conducta | Ídem (formato `id \| tema1, tema2 \| regla`) |
| 🗓️ Agenda | Bloques (`dias \| inicio \| fin \| actividad`), respuestas libres y zona horaria |
| ⚙️ Operación | Datos internos del negocio que Diana recibe solo cuando el cliente menciona un alias (formato `id \| alias1, alias2 \| hecho`) |
| 🕘 Historial | Lista de versiones con fecha y botón de restauración (con confirmación) |

### Escribir con tus palabras y revisar antes de guardar

En **Datos personales, Políticas, Patrones de voz, Operación y Bloques de agenda**
ya no hace falta el formato con `|`: la dueña escribe la regla con sus palabras
("tengo un perro que se llama Toby") y el bot arma una **vista previa** con el
elemento propuesto (id, temas, texto) y el **canal** (VIP / Atención). Nada se
guarda hasta tocar un botón:

- **✅ Guardar**: guarda el elemento tal como se ve, como versión nueva, en el
  canal de la vista previa.
- **✏️ Corregir**: descarta la propuesta y pide el texto de nuevo. Escribir otro
  texto mientras se ve la vista previa hace lo mismo.
- **➕ Nota privada** (solo Datos personales): agrega una nota que Diana **no usa
  para responder** y que **nunca se envía a la IA**. La vista previa solo dice
  "🔒 Nota privada: sí", sin mostrar el texto. La nota agregada se conserva al
  tocar Corregir.
- **✖️ Cancelar**: vuelve a la lista sin guardar.

Cómo se arma la propuesta: el texto va al mismo proveedor de IA que usa Diana,
con una espera máxima de 10 segundos y solo con lo necesario (la sección, el
texto, los temas ya usados, los ids existentes y, si se edita, los campos
públicos de ese elemento), siempre del catálogo del canal donde se escribe. Si la
IA no responde, propone algo inválido o su propuesta no pasa la validación del
catálogo, se arma una propuesta sin IA con el mismo texto. Si tampoco esa es
válida, el panel explica el motivo en español. La propuesta se valida igual que
un guardado (temas en forma canónica, alias de Operación permitidos) antes de
mostrarse.

El formato con `|` sigue funcionando y también pasa por la vista previa: produce
el mismo elemento que antes y el texto se guarda tal cual se escribió (emojis,
«nº», «m²», «½» y letras de ancho completo no cambian). Lo único nuevo en `|` es
la revisión de notas privadas descrita más abajo.

Detalles de la vista previa:

- **Cambiar de canal cierra** cualquier alta, edición o vista previa abierta.
- Los botones solo valen para la vista previa que muestran. Un botón de una vista
  previa anterior (por ejemplo, tras reabrir /menu) no guarda nada y el panel
  avisa que ya no vale.
- La vista previa expira a los 15 minutos sin uso; Guardar entonces avisa que
  expiró y no guarda.
- Si llega un segundo texto mientras se prepara la vista previa, el bot responde
  «⏳ …» y ese segundo texto no se guarda en cola: hay que reenviarlo o usar
  Corregir cuando aparezca la vista previa.
- Al editar un Dato, el panel solo indica que tiene nota privada ("🔒 Tiene nota
  privada…"), sin mostrar su texto, y ese texto nunca se envía a la IA.
- Editar un Dato **con tus palabras** conserva su nota privada. Editarlo con
  `|` **sin** 4.º campo la borra, igual que antes de este cambio (pendiente de
  decisión de la dueña).
- "Cómo habla Diana", Reglas de tono, Respuestas libres de Agenda y Zona horaria
  se siguen guardando directo, sin vista previa.

### Notas privadas: qué se reconoce y dónde

Toda la detección vive en una sola función, `split_private_note(text, *, path,
section)` (`src/diana/telegram/handlers/persona_admin.py`). La llaman solo tres
caminos:

| Camino | Qué revisa |
|--------|-----------|
| Texto libre (`_draft_free_text`) | El texto de Datos personales, Políticas, Patrones de voz, Operación y Agenda, **antes** de enviarlo a la IA |
| `\|` de Datos personales (`_parse_fact`) | El 3.er campo (hecho) |
| `\|` de las otras cuatro secciones (`_handle_preview_text`) | Cada campo (solo revisa; la línea se guarda como antes) |

**No cubre** (se guarda directo, sin revisión ni vista previa): **Cómo habla
Diana, Reglas de tono, Respuestas libres de Agenda y Zona horaria**. Una nota
privada escrita ahí se guarda y Diana puede usarla, y una respuesta libre de
Agenda puede llegar tal cual a un cliente. Ya pasaba antes; está registrado como
riesgo de privacidad y se atenderá en un pool nuevo (ver "Limitaciones
conocidas"). Tampoco revisa el texto que se escribe tras **➕ Nota privada** ni el
4.º campo de un Dato con `|`: eso **es** la nota y se guarda tal cual.

Contrato:

1. La búsqueda del marcador se hace sobre una **copia normalizada** del texto
   (NFKC, sin caracteres invisibles de formato, cualquier tipo de salto de línea
   leído como salto). Lo que se guarda es siempre el **texto original**: sin
   marcador, idéntico (solo se recortan espacios de las orillas); con marcador,
   se corta el original en ese punto.
2. La palabra se reconoce como «nota privada» con plural, «privado», mayúsculas,
   `nota_privada` o `nota-privada`. En Datos personales es **marcador** solo así:
   - seguida de «:» **en cualquier posición**, también entre paréntesis o
     comillas: «Laura tiene gastritis, nota privada: no lo menciones»,
     «(Nota privada: se llama Juan)»;
   - seguida de un guion («-», «–», «—») **solo** al inicio del texto o del campo,
     o justo después de un punto, un punto y coma o un salto de línea: «Tengo un
     hermano. Nota privada - se llama Juan». «Guardo mis notas privadas - las
     releo» **no** es marcador en Datos;
   - entre paréntesis, «(nota privada)», con o sin «:» después.
3. **Datos personales** (texto libre y hecho de `|`): lo que sigue al primer
   marcador es la nota privada; lo anterior, el hecho.
4. **Políticas, Patrones de voz, Operación y Agenda** no tienen nota privada: se
   **rechaza** el texto si «nota privada» va seguida de «:» o de un guion **en
   cualquier parte**, o si aparece «(nota privada)», en texto libre y en `|`. Una
   mención sin «:», guion ni paréntesis se acepta.
5. Solo en el **texto libre de Datos**: si se menciona una nota privada sin
   marcador, el panel pide aclararlo y no envía nada a la IA. En `|` esa mención
   es texto normal.

## Vocabulario por canal

En cada turno el Analyst recibe, además de su lista fija, el vocabulario del
**catálogo activo del canal** de la conversación (VIP o atención; cada canal solo
ve el suyo): los temas de Datos personales, los temas de Políticas y los tags de
Patrones de voz. Así una regla o un patrón que la dueña agregue con un tema nuevo
sí se puede recuperar.

- Temas y tags se comparan en forma canónica: sin acentos, en minúsculas y con
  `_` ("Precios especiales" = `precios_especiales`, "cariño" = `carino`). Al
  guardar también se escriben así; el primer guardado de cada canal reescribe los
  temas antiguos. Los alias de Operación no se reescriben.
- Tope de 60 términos por turno, repartidos de forma justa entre las tres
  secciones; si hay que recortar, cada sección conserva sus primeros términos y se
  registra `analyst_catalog_vocab_truncated` (nivel INFO).
- En atención, el Analyst sabe que la lista fija de temas de política del prompt
  es del canal VIP.

## Operación: alias

Con `FEATURE_PERSONA_OPERACION_ENABLED` encendido (apagado por defecto), cuando el
mensaje del cliente contiene un alias como palabra o frase completa, Diana recibe
el hecho de ese elemento. Tope por turno `PERSONA_OPERACION_MAX_PER_TURN` (por
defecto 2, máximo 5).

- Los artículos y palabras de relleno al inicio o al final del alias son
  opcionales: "El Diván" responde a "diván" y a "tu diván"; las del medio se
  conservan ("el canal de ventas").
- Regla del alias (sobre esa parte central): al menos 4 letras, o 3 si es un
  nombre propio escrito con mayúscula ("Ana"); no puede ser una palabra común
  ("bot", "canal", "Sol", "Mar"…), ni chocar con un tema de Datos personales del
  mismo canal ("mi familia" choca con `familia`).
- Si varios elementos coinciden, gana el alias más específico (más letras, luego
  más palabras, luego el orden de la lista).
- Al guardar solo se revisan los alias nuevos o cambiados. Un alias guardado que
  ya no cumple la regla no impide guardar: Diana lo ignora y el panel lo marca con
  ⚠️ y explica por qué.
- Se rechaza guardar un Dato cuyo tema apagaría un alias que hoy funciona (el
  panel dice qué alias y pide otro tema).
- En saludos, check-ins y preguntas repetidas no se usa Operación. Lo que se
  inyectó solo queda en la traza en memoria del turno; no se guarda en la base.

## Vector de las reglas aprendidas (zona gris)

Las reglas que Diana aprende de la zona gris (en vivo o al promover un candidato
de staging) se guardan con un vector para buscarlas por significado.

- El modelo de vectores se precarga en segundo plano al arrancar
  (`embedding_warmup_done` / `embedding_warmup_failed`); el bot atiende de
  inmediato y, si la precarga falla, el modelo se carga con el primer uso.
- Si el vector falla al aprender una regla, se reintenta una vez; si vuelve a
  fallar, la regla se guarda igual con un **marcador de vector vacío** y se
  registra `policy_embedding_pending`.
- Al arrancar y luego cada 30 minutos se reparan hasta 50 reglas **activas** con
  ese marcador (`policy_embedding_repair` con encontradas / reparadas / fallidas;
  WARNING si alguna falló). Nunca se escribe un vector vacío. Sin migración.
- Pendiente: los ejemplos y perfiles todavía pueden quedar con vector vacío, y
  las reglas inactivas con marcador no se reparan.

## Búsqueda por significado en sombra (`FEATURE_PERSONA_SEMANTIC_SHADOW`)

Medición para decidir si conviene buscar el catálogo también por significado.
**Apagada por defecto** (`FEATURE_PERSONA_SEMANTIC_SHADOW=false`); apagada, ni
siquiera se crea.

- Encendida, después de que el turno arma su contexto, se lanza **en segundo
  plano** una comparación del mensaje del cliente con el catálogo del canal. El
  turno nunca la espera y el prompt queda idéntico byte a byte.
- Se indexan Datos personales (temas + hecho), Políticas (temas + regla) y
  Operación (alias + hecho). Nunca la nota privada; los Patrones de voz no se
  indexan.
- Resultado: log `persona_semantic_shadow` con los 3 elementos más parecidos (ids
  y puntaje), si ya se habían recuperado (`already_retrieved`), `embed_ms` y
  tamaño del índice. Sin texto del cliente y sin escribir en la base.
- Una tarea por canal a la vez: si hay una en curso, la nueva se descarta
  (`persona_semantic_shadow_dropped`). Si el modelo aún no está cargado, se salta
  (`persona_semantic_shadow_skipped`); la sombra nunca dispara la carga.
- `scripts/persona_shadow_misses.py` lee esos logs (solo lectura) y lista los
  aciertos por significado que la búsqueda por temas/alias no recuperó.
- Encenderla en producción es decisión de la dueña; antes conviene medir
  `embed_ms` y CPU en el servidor.

## Limitaciones conocidas (privacidad, diferidas a un pool nuevo)

Decisión de la dueña (2026-10-02 21:41 CST): estos casos se atienden en un pool
aparte. Hasta entonces, **no escribas notas privadas** fuera de "➕ Nota privada"
o del formato documentado.

- Cómo habla Diana, Reglas de tono, Respuestas libres de Agenda y Zona horaria no
  revisan notas privadas.
- En un `|` de Datos, «…, nota privada - X» (guion tras coma o a mitad de frase)
  se guarda como hecho público.
- Grafías parecidas o invisibles no se reconocen (letras cirílicas, acentos dentro
  de la palabra, la palabra pegada a la anterior, ciertos rellenos invisibles).
- El signo menos «−» como guion y «。» antes del guion no cuentan.
- Sinónimos como «Privado:», «Notas personales:», «Confidencial:» o «(privado)»
  no cuentan como marcador.
- En Políticas, Patrones, Operación y Agenda, «Nota privada X» sin «:», guion ni
  paréntesis se acepta.
- «[nota privada] X» con corchetes: falta confirmar el comportamiento en todas las
  secciones.

## Reglas del producto (no negociables)

1. **Cada cambio se guarda como versión nueva** en la base de datos. El historial
   permite volver atrás en un toque. El archivo de fábrica (`persona_diana.json`)
   queda intacto como "versión cero".
2. **Aplica al instante**: el siguiente mensaje que procesa el bot ya usa los
   cambios; no hay que reiniciar nada.
3. **Solo la dueña** puede editar (mismo acceso privado que el resto del panel).
4. **Con la sección apagada (flag off) el bot se comporta exactamente como antes**:
   catálogo estático, cero consultas extra a la base.
5. Si una edición queda mal formada, el bot **no guarda** y muestra el motivo
   para corregirlo.

## Notas operativas

- Activar: `FEATURE_PERSONA_ADMIN_ENABLED=true` en la config del servidor y reiniciar.
- Si la base de datos no está disponible al leer la personalidad, el bot usa la
  versión estática y lo reintenta en el siguiente turno (no crashea).
- Límites de la UI: las listas muestran hasta 40 elementos y el historial 30
  versiones (los más recientes); el resto sigue guardado en la base.

## Implementación (mapa)

| Slice | Item | Superficies |
|-------|------|-------------|
| Persistencia versionada + validación pura | item1 | migración `017_persona_versions`, `PersonaVersionRepo`, `PersonaAdminService`, `validate_persona_catalog` |
| Catálogo vivo (hot-reload) | item2 | `PersonaCatalogProvider` (cache + invalidación), retrievers con refresh por identidad, `CognitiveDirector` por turno |
| Panel Telegram | item3 | `handlers/persona_admin.py`, categoría `m:personalidad:*`, wizards `persona_edit`, keyboards |
| Docs + e2e | item4 | este documento, `tests/e2e/tier2/test_persona_versions_e2e.py` |
| Vocabulario por canal (pool `persona-reglas`) | 1 | `cognitive/tags.py` (`normalize_tag`, `fair_share_limits`), `cognitive/analyst.py` (`_catalog_addendum`), `cognitive/director.py` |
| Alias de Operación | 2 | `cognitive/operacion.py` (`alias_core`, `alias_problem`, `validate_operacion_semantics`, `match_operacion`), `PersonaAdminService`, avisos ⚠️ del panel |
| Vector de zona gris + precarga | 3 (D) | `cognitive/embedding.py`, `application/policy_embedding.py`, `jobs/embedding_warmup.py`, `PoliciesRepo` |
| Captura con vista previa | 3 (C) | `application/persona_rule_drafter.py`, `handlers/persona_admin.py` (`split_private_note`, vista previa), `keyboards.py` |
| Sombra semántica | 3 (E) | `cognitive/persona_semantic.py`, `config/settings.py`, `composition.py`, `scripts/persona_shadow_misses.py` |

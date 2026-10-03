# Product Owner — Personalidad y reglas (panel de Telegram)

**Status:** **IMPLEMENTED** (pool `persona-admin` closed 2026-08-04)
**Project:** DianaV2
**Source:** owner conversation + decisiones de la dueña (guardado en base con historial;
todo desde el inicio; aplica sin reiniciar)
**Audience:** dueña del producto + implementadores
**Pool evidence:** `.planning/quick/persona-admin/`

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
elemento propuesto (id, temas, texto). Nada se guarda hasta tocar un botón:

- **✅ Guardar**: guarda el elemento tal como se ve, como versión nueva.
- **✏️ Corregir**: descarta la propuesta y pide el texto de nuevo. Escribir otro
  texto mientras se ve la vista previa hace lo mismo.
- **➕ Nota privada** (solo Datos personales): agrega una nota que Diana **no usa
  para responder** y que **nunca se envía a la IA**. La vista previa solo dice
  "🔒 Nota privada: sí", sin mostrar el texto. Al editar un dato con tus palabras,
  su nota privada se conserva.
- **✖️ Cancelar**: vuelve a la lista sin guardar.

Cómo se arma la propuesta: el texto va al mismo proveedor de IA que usa Diana,
con una espera máxima de 10 segundos y solo con lo necesario (la sección, el
texto, los temas ya usados, los ids existentes y, si se edita, los campos
públicos de ese elemento). Si la IA no responde o propone algo inválido, se arma
una propuesta sin IA. El formato con `|` sigue funcionando igual y también pasa
por la vista previa. La propuesta se valida igual que un guardado (temas en forma
canónica, alias de Operación permitidos) antes de mostrarse. La vista previa
pertenece al canal (VIP / atención) donde se escribió: cambiar de canal la
descarta. "Cómo habla Diana", Reglas de tono, Respuestas libres y Zona horaria
se siguen guardando directo.

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

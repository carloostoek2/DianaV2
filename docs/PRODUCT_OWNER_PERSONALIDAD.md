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
| 🕘 Historial | Lista de versiones con fecha y botón de restauración (con confirmación) |

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

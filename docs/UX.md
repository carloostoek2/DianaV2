# UX de la dueña — estado actual (Telegram)

La dueña opera Diana **solo por Telegram**, en el DM privado con el bot. Este documento describe el comportamiento **actual** en `main` (2026-08-16), no hallazgos abiertos.

Principio: cada acción que pide texto tiene escape (`/cancelar`) y TTL (15 min). Cada error deja un botón de salida. Borrar datos pide confirmación.

## Quick path — aprobar un borrador VIP

1. Llega un DM: `Propuesta de respuesta para {nombre del VIP}` (si no hay nombre, el `chat_id`) + texto del VIP + borrador + scores.
2. Tocar **✅ Aprobar**. El botón deja de girar al instante (`query.answer()` vacío, A3).
3. El mismo mensaje se edita en vivo: `👀 Mensaje visto` → `✍️ Escribiendo…` (botones todavía visibles).
4. Al terminar: `✅ Enviado` y se quitan los botones.

Si el turno ya no aplica, el toast dice **por qué** (reemplazado, ya enviado, ya resuelto, cancelado, no encontrado, VIP congelado). No hay un “ya fue resuelto” genérico.

## Teclado del borrador

Fila 1 (siempre): **Aprobar** · **Corregir** · **Escalar**.

Fila 2 (solo si `FEATURE_QUALITY_FEEDBACK_ENABLED=true` **y** el turno tiene `vip_id`): **Destacar** · **Reprender**. En canal atención o con el flag apagado (default) esa fila no existe.

Fila 3: **◀ Anterior** · **🔄 Regenerar** · **Siguiente ▶**.

Fila 4: **🔍 Traza** (vuelve al borrador con `tb:`) · **📝 Agregar nota**.

### Corregir

1. Tocar Corregir abre una sesión de 15 min.
2. El bot pide el texto corregido. `/cancelar` o un comando abortan.
3. El texto se entrega al VIP y queda un candidato `pending` en staging (la dueña lo revisa después en Métricas → Ejemplos pendientes).

### Destacar (flag ON, solo VIP)

1. Tocar Destacar **no** envía todavía. El teclado pasa a **🌍 General** / **👤 Este VIP** / **⬅️ Volver**.
2. Al confirmar el alcance: se aprueba (misma entrega que Aprobar, con progreso en vivo) y se inserta un ejemplo `quality='gold'` sin pasar por la cola de staging.
3. Sandbox: se entrega, no se persiste el gold. Atención: se bloquea antes de enviar.

### Reprender (flag ON, solo VIP)

1. Tocar Reprender pide el texto. Copy: el VIP lo recibe al instante; después se elige cómo guardar la lección.
2. Al enviar el texto se **entrega ya** (`handle_correct_with_candidate`) y queda un candidato interno.
3. Aparece el combo **solo promoción** (el VIP ya tiene el mensaje):

   | | General | Este VIP |
   |---|---|---|
   | Regla dura (política) | `rpc:…:pol:g` | `rpc:…:pol:v` |
   | No repetir (contraejemplo) | `rpc:…:ex:g` | `rpc:…:ex:v` |

4. Si el VIP escribe de nuevo, el combo se cancela (`cancel_combo_for_chat`). El texto ya enviado no se revierte.
5. Si el combo expira o llega un `rpc:` huérfano: “No se guardó la lección. El texto ya se envió al VIP.” Fail-closed: no se vuelve a entregar.

Detalle de bancos y flag: ver el concepto de calidad-feedback en la wiki.

### Regenerar y versiones

- **🔄 Regenerar** muestra `♻️ Regenerando…` **solo** cuando el run arranca de verdad (después del soft-lock). Un toque stale no parpadea la leyenda.
- Si falla, se restaura el cuerpo original. Si sale bien, el notifier reemplaza el DM con la nueva versión.
- Toasts: “Nueva versión lista”, “Espera a que termine la regeneración”, “Máximo de versiones alcanzado”, “Primera/Última versión”.

### Traza desde el borrador

**🔍 Traza** abre el resumen del turno (`vtd:`). Los pasos usan `tdd:`. **🔙 Volver al borrador** (`tb:`) reedita el DM de aprobación si el approval sigue `waiting`; si no, alerta “Borrador no disponible”.

Desde `/turnos`, **🔙 Volver a turnos** restaura la **página exacta** (`vt:<id>:N`). La lista tiene **🔙 Volver al menú**.

## Consulta de doctrina (zona gris)

Teclado del DM de consulta (`doctrine_keyboard`):

- **📝 Responder consulta** (`dr:`) — abre sesión 15 min. El siguiente texto del DM es a la vez el texto que recibirá el VIP y la regla para casos futuros.
- **✅ Usar borrador** (`dx:`) — resuelve con el draft persistido.
- **⚠️ Escalar** (`de:`).

Si el bot no puede avisar a la dueña en un turno **VIP** (`send_doctrine_query` falla), no deja al VIP congelado 24 h: descarta la query (descongela) y degrada a `approve` con `reason=vip_doctrine_notify_failed`, y reenvía el borrador normal. Mismo patrón que el canal atención (F6).

## Menú de la dueña (`/start` o `/menu`)

`🌸 Panel de Diana` — un solo mensaje que se edita in-place (no acumula paneles).

| Categoría | Qué hay |
|---|---|
| 👥 Mis VIPs | Lista, registrar (reenvío + confirmación con TTL), ficha, nota/dato, renombrar, pausar (1 día / 3 días / 1 semana / 1 mes / indefinido), desactivar con confirmación. Ficha: un 🗑 por nota/dato. VIP desactivado desde un botón viejo → aviso + vuelta a la lista (A13). |
| 💬 Revisar mensajes | Recuerda que Aprobar/Corregir/Escalar viven en el borrador. Aquí solo **🚩 Marcar falsa alarma**. |
| 🧪 Modo de prueba | Activar (reenvío + perfil), desactivar, perfiles, estado, reiniciar. Flag `FEATURE_SANDBOX_ENABLED` (default OFF). |
| 📊 Métricas y aprendizaje | Resumen semanal + export JSON como **documento** (`metricas_semanales.json`, sin tope 4096). Ejemplos pendientes (staging: promover / descartar en **dos pasos**). |
| 🔍 Historial y diagnóstico | Turnos recientes + detalle de traza + export JSON. |
| 📅 Eventos temporales | Contexto con vigencia (crear / pausar / terminar / eliminar). |
| 🎭 Personalidad y reglas | Solo si `FEATURE_PERSONA_ADMIN_ENABLED`. Canal VIP / Atención. |
| ⚙️ Configuración | Toggle Modo Entrenamiento. |

Sesiones de texto (nota, dato, nombre, reenvío, doctrina, corregir, reprender): TTL 15 min. Si vencen, el bot dice “Tu operación expiró, vuelve a intentarlo.” — no traga el texto (A6). `/cancelar` aborta. Un comando escrito a mitad de wizard no se convierte en nota (A1/A2).

Confirmaciones de registrar/desactivar VIP caducan a 15 min (A7). Descartar un candidato de staging: primer toque arma “¿Sí, descartar?”; el segundo borra (A4). Memoria sensible: toast de descarte con alerta.

## Mensajes que el modelo ve (inbound)

Un archivo sin caption ya no llega vacío. El handler de negocio antepone un tag de tipo y deja el caption si existe:

| Tipo Telegram | Tag |
|---|---|
| photo | `[imagen]` |
| video / video_note | `[video]` |
| audio | `[audio]` |
| voice | `[voz]` |
| document | `[documento]` |
| animation | `[gif]` |
| sticker | `[sticker]` |

## Thinking del LLM (ops, no es un botón)

`LLM_THINKING_ENABLED` default **ON**. Aplica solo a `generate()` (borradores de texto libre) con esfuerzo **low**; si el CoT agota el presupuesto de tokens y el mensaje sale vacío, hay un reintento con la misma config y, si falla igual, un fallback con thinking apagado. Presupuestos cortos (p. ej. recontacto) saltan thinking. El flag sigue siendo el interruptor maestro solo para borradores. Analyst/Evaluator (`generate_structured`) llevan thinking **siempre apagado**, independiente del flag.

## Tokens honestos (Aprobar / Corregir / Escalar)

| Token | Toast |
|---|---|
| `stale_replaced` | Este borrador ya no aplica (mensaje nuevo o se reemplazó). No se envió. |
| `stale_already_sent` | Este mensaje ya se había enviado — no se hizo nada. |
| `stale_resolved` | Este turno ya se resolvió — no se hizo nada. |
| `stale_cancelled` | El borrador ya no está disponible — no se envió. |
| `stale_gone` | No se encontró el turno — no se hizo nada. |
| `vip_frozen` | El VIP está en pausa/congelado — no se envió. |
| `stale` | Ya fue resuelto o reemplazado — no se realizó ninguna acción |

## Hardening A1–A13 — cerrado (2026-08-12, `2b39c83`)

Los hallazgos de la auditoría UX ya no están abiertos. Comportamiento vigente:

| ID | Antes (bug) | Ahora |
|---|---|---|
| A1 | Nota desde borrador sin TTL ni `/cancelar` | `MenuSessionStore` kind `note`, 15 min, prompt con “Usa /cancelar para abortar.” |
| A2 | Wizard hacía pop antes de validar | Sesión vive hasta éxito o cancelar; input inválido re-pide |
| A3 | Spinner durante entrega | `query.answer()` vacío al llegar; alertas tardías solo en no-op / error |
| A4 | Descartar staging/memoria a un toque | Staging: confirmar ✅/❌. Memoria: toast con `show_alert` |
| A5 | Errores con `keyboard=None` | Todo error de menú lleva **🔙 Volver**. Los prompts de texto usan `/cancelar` |
| A6 | Sesión vencida tragaba el texto | Aviso “Tu operación expiró…” |
| A7 | Confirm delete/register eternos | TTL 15 min + alerta si expiró |
| A8 | Export métricas como texto (rompe >4096) | Documento JSON completo |
| A9 | No se podían borrar notas/datos del menú | 🗑 por item en la ficha |
| A10 | Back de métricas apilaba paneles; traza iba a página 0; `/turnos` sin salida | Edit in-place; página en el callback; Volver al menú |
| A11 | Copy sin tildes, typo “marar”, botón de 37 chars | Acentuación alineada; “🔄 Reiniciar prueba”; “marcar falsa alarma” |
| A12 | `/start` duplicado (texto legacy) | Solo el router de `menu.py` |
| A13 | `m:vip` de un VIP desactivado seguía mostrando acciones | Redirect a la lista con aviso |

Slash commands legacy (`/add_vip`, `/list_vips`, `/vip_*`, `/sandbox`, `/turnos`, `/traza`, `/fp`, `/resumen`, `/staging`) siguen vivos como alias. El camino que ve la dueña es el menú + los botones del borrador.

## Checklist

- [ ] Flag de calidad OFF → el borrador VIP no muestra Destacar/Reprender.
- [ ] Destacar pide alcance antes de enviar.
- [ ] Reprender envía el texto ya; el combo solo guarda la lección.
- [ ] Aprobar muestra leído → escribiendo → enviado.
- [ ] Regenerar muestra Regenerando solo si el run arranca.
- [ ] Un no-op dice la causa real.
- [ ] Traza desde el borrador vuelve al borrador.
- [ ] Nota / doctrina / corregir se pueden abortar con `/cancelar` o esperando 15 min (con aviso).

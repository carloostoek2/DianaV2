# FASE 2 — Historial: importación desde la cuenta personal

**Contrato:** C-HIST-01 (b) — "El historial previo del VIP se importa desde la cuenta de
Telegram de la dueña, lentamente, un VIP por ciclo".
**Rama:** `main` (integrado el 2026-10-07 desde `audit/historial-decision`). **Fecha:** 2026-10-07.

Documenta la decisión de producto sobre la importación de historial desde la cuenta personal de
Telegram, el estado final del alta de un VIP nuevo, y la verificación con efecto real.

---

## 1. Decisiones de producto vigentes

| Fecha | Decisión | Estado |
|---|---|---|
| 2026-09-06 | **Recarga de historial de VIP ya registrados: apagada.** `FEATURE_HISTORY_REIMPORT_ENABLED=false` | Vigente |
| 2026-09-06 | **Importación de historial al registrar un VIP nuevo: apagada.** `FEATURE_VIP_HISTORY_SEED_ENABLED=false` | Vigente |
| 2026-10-07 | **El historial compartido entre la cuenta anterior y la cuenta en uso se usa a propósito**, porque es el mismo cliente y la misma relación comercial | Vigente |

**Motivo de las dos primeras:** la sesión de Telethon configurada (`TELETHON_SESSION_PATH`) es de
la **cuenta anterior**, y la cuenta en uso (creada el 8 de septiembre) **no tiene historial con
ningún VIP**: todos escriben en chats nuevos. Consultar Telegram con esa sesión solo traería la
conversación vieja y generaría actividad de una cuenta recién creada. El historial anterior
**sigue guardado** en `message_history`; no se borró nada.

**Condición para reactivar cualquiera de las dos:** que `TELETHON_SESSION_PATH` apunte a una
sesión de la **cuenta en uso** y que la dueña decida de forma explícita asumir el riesgo de que
Telegram note la actividad. No hay reactivación automática ni por fecha.

**Alcance de la tercera decisión:** las filas de la cuenta anterior en `message_history` (bajo el
id de Telegram de la persona) son legítimas y se usan a propósito; no son contaminación ni un
defecto, y un revisor que las encuentre no debe borrarlas, filtrarlas por fecha ni por cuenta sin
una decisión de producto nueva. Esa vía (base → perfil, reproceso de memoria) **no lleva
bandera y no debe llevarla**: no es una importación, es el uso normal del historial. Las dos
banderas gobiernan otra cosa: la consulta a Telegram con la cuenta personal.

---

## 2. Qué hace el alta de un VIP nuevo (estado final)

| Pregunta | Respuesta | Sustento |
|---|---|---|
| ¿Bloquea o retrasa el alta? | **No.** El alta se guarda primero; la importación era una tarea de fondo que el handler no esperaba | `vip_history_seed.py` |
| ¿Falla el alta si la importación falla? | **No.** Cualquier excepción se captura y se convierte en un resultado fallido | `vip_history_seed.py` |
| ¿Consulta Telegram con la cuenta personal? | **No.** Con la bandera apagada el importador ni se construye: configurar las credenciales ya no alcanza para activarlo | `composition.py`, verificado en producción |
| ¿Avisa a la dueña? | **No**, por diseño. Apagado a propósito no genera ruido en el chat de la dueña | `vip_history_seed.py` |
| ¿Deja rastro? | **Sí.** `vip_history_seed_disabled_by_flag` al arrancar (con `session_path` y motivo) y `vip_history_seed_skipped_disabled` en cada alta, con el id del VIP y `reason="flag_off"` | `composition.py`, `vip_history_seed.py` |

El servicio se sigue construyendo con la bandera apagada (los dos puntos de alta no cambian): lo
que no existe es el importador.

---

## 3. El caso real medido: Memo L.A.

Único VIP registrado en el bot desde el cambio de cuenta. Es el caso donde la importación seguía
encendida y, por lo tanto, donde se puede ver qué pasaba de verdad.

### 3.1 Línea de tiempo (hora local; la base guarda UTC)

| Momento | Hecho | Registro |
|---|---|---|
| 21/09 18:37:52 | Ficha del VIP creada | `vips.created_at` = 2026-09-22 00:37:52 UTC |
| 21/09 18:37:53 | La sesión de Telethon se abre | `runtime/diana_session.session`, fecha de modificación |
| 21/09 18:37:53 | Reproceso de perfil encolado (paso 0) | `backfill_queue` |
| 21/09 18:37:55 | Perfil generado (3 s después del alta) | `memories`, `"fuente": "backfill"` |
| 21/09 23:27:53 | Segundo encolado ("en cola — se procesará en ~2 pasos") | `backfill_queue`, paso 1 |
| 22/09 00:28 | Perfil regenerado (una hora justa después: el ritmo de la cola) | `memories`, `"fuente": "backfill"` |

### 3.2 Qué se importó desde Telegram: nada

El intento **sí se ejecutó y sí conectó** (la sesión se abrió un segundo después del alta), pero
**no agregó ninguna fila** a `message_history` y **no envió ningún aviso**. La sesión no se volvió
a tocar después de esa marca.

Causa de fondo, corregida: la tarea de fondo se creaba **sin guardar referencia**, a diferencia
de la del reproceso de perfil, que sí la guarda. Una tarea sin referencia puede recolectarse a
mitad de ejecución. La causa exacta del caso concreto (tarea perdida o consulta que quedó
esperando) no es determinable: los registros de esa fecha quedaron fuera de la retención de
`journald`.

### 3.3 De dónde salió la información del perfil: de la base

- Las memorias se crearon 3 segundos después del alta, con `"fuente": "backfill"`. El reproceso
  lee `message_history`; no usa Telethon.
- Entre los hechos extraídos hay referencias al **15 de septiembre**, anteriores al alta.
- La sesión de Telethon, en cambio, no aportó ninguna fila.

**Mecanismo:** `message_history` está indexado por el **id de Telegram de la persona**, no por
cuenta ni por chat. Al cambiar de cuenta, el mismo id conserva el historial de la cuenta anterior
mezclado con el de la cuenta en uso. En el chat de Memo L.A.:

| Periodo | Ids de mensaje de Telegram | Cuenta |
|---|---|---|
| Agosto (9, 12 y 15) | 593.820 – 602.844 | Anterior |
| Desde el 8 de septiembre | 2.582 en adelante | En uso |

Todo bajo el mismo `chat_id`. La primera pasada del perfil (18:37) tomó el tramo más antiguo —el
historial anterior al alta— y por eso el perfil sabe cosas de agosto y de septiembre.

### 3.4 Un límite conocido del historial previo

De todo el historial de ese chat anterior al alta había **206 mensajes de Diana y cero del
cliente**: la base guarda el lado del cliente solo cuando la persona ya está registrada; antes de
eso queda únicamente lo que Diana escribió. El perfil se armó, entonces, leyendo la mitad de la
conversación. Por eso hay hechos deducidos de las palabras de Diana (por ejemplo, un pago
informado por ella) sin que esté la respuesta del cliente. Queda como está: es el comportamiento
actual del sistema, no una tarea pendiente.

---

## 4. Cambio aplicado

1. **`Settings.feature_vip_history_seed_enabled: bool = False`** (`config/settings.py`). El valor
   real vive en el `.env` (regla de prioridad de `AGENTS.md` §1).
2. **`composition._build_vip_history_seed`**: el importador solo se construye con la puerta
   encendida **y** credenciales presentes. La configuración de Telethon ya no alcanza por sí sola.
3. **Registro explícito** del motivo, al arrancar y en cada alta.
4. **Sin aviso a la dueña** cuando la puerta está apagada.
5. **`.env`**: comentario de la recarga corregido (decía "VIVO desde 2026-09-02" con el valor real
   en `false`) y bandera nueva con motivo y condición de reactivación. Ningún otro valor cambió.
6. **Referencia viva de la tarea** (`vip_history_seed.py`): la tarea del alta se sostiene en un
   conjunto y se suelta al terminar, igual que `MemoryBackfillQueue`. Corrige el defecto de §3.2.

---

## 5. Verificación

Prueba E2: `tests/audit/test_C_HIST_01.py`. Entra por el comando real de alta (`/add_vip`) sobre el
contenedor armado por `build_app`, contra Postgres real. Solo se simulan las dos fronteras
externas: la sesión de Telethon y la salida de mensajes a Telegram.

Aserciones con la puerta apagada y credenciales de Telethon presentes:

1. El alta quedó en `vips` (efecto real en la base).
2. `message_history` no recibió ninguna fila para ese chat.
3. El importador de Telethon **nunca se construyó**.
4. Existen los dos registros con el motivo.
5. La dueña no recibió ningún aviso.
6. La respuesta del alta sí salió (el alta corrió de verdad, no es un no-op).

Contraprueba en la misma suite: con la puerta **encendida**, el importador sí queda cableado. Sin
ella, la prueba principal podría pasar por una pieza rota en lugar de por una puerta cerrada. No
se envía ningún mensaje, así que no se abre ninguna sesión real.

### Sabotajes (E3)

| Sabotaje | Qué se desconectó | Resultado |
|---|---|---|
| S1 | La puerta de la bandera en `composition.py` | La prueba principal **falla**: el importador se construye y el alta lo llama |
| S2 | El registro explícito del alta | La prueba principal **falla**: falta el registro con el motivo |
| S3 | La referencia viva de la tarea | La prueba unitaria **falla**: `la tarea quedó sin referencia` |

### Matriz de banderas

| `FEATURE_VIP_HISTORY_SEED_ENABLED` | Efecto en el alta |
|---|---|
| `false` (valor actual) | No se construye importador, no se toca Telegram, queda registro del motivo, sin aviso a la dueña |
| `true` | El importador se cablea; el alta consulta la sesión personal y avisa a la dueña con el resultado |

`FEATURE_HISTORY_REIMPORT_ENABLED` no interviene en el alta: con la puerta del seed apagada, el
servicio de recarga tampoco se construye.

Suites ejecutadas: `tests/audit`, `tests/unit` — **4352 pruebas en verde**.

---

## 6. Estado en producción

**Activo desde el 2026-10-07 07:16 UTC**, sobre `main` (`fc98be7`), publicado en `origin/main`.
Reinicio verificado con el bot respondiendo y sin reinicios en bucle. Registro de arranque:

```
vip_history_seed_disabled_by_flag session_path=.../runtime/diana_session
  telethon_configured=True reason=feature_vip_history_seed_enabled=false
history_reimport_job_skipped_flag_off
```

`telethon_configured=True` deja ver que la configuración de Telethon sigue completa: lo que impide
la importación es la puerta de producto, no una credencial faltante.

---

## 7. Límites de esta verificación

- **No se consultó la sesión real de Telethon.** Provocar actividad de la cuenta anterior es
  justamente lo que la decisión busca evitar. Esa frontera se simula en la prueba.
- **La contraprueba no ejecuta una importación real** (no hay sesión autorizada de la cuenta en
  uso): solo verifica que la pieza se cablea cuando la puerta se enciende.
- **Los registros de producción cubren ~7 días**, así que las altas anteriores al 2026-09-30 no
  son observables por esa vía.

---

## 8. Vigilante propuesto (E4)

1. **Alerta si el importador se cablea con la puerta apagada.** Buscar `vip_history_seed_enabled`
   en el arranque mientras `FEATURE_VIP_HISTORY_SEED_ENABLED=false`, o cualquier
   `vip_history_seeded` en operación normal.
2. **Alerta si aparece historial anterior al alta.** Filas de un VIP con fecha de mensaje anterior
   a su fecha de alta son la huella de una importación desde la cuenta anterior:

```sql
select v.telegram_user_id, v.created_at::date as alta, min(m.timestamp)::date as primer_mensaje
from vips v
join message_history m on m.chat_id = v.telegram_user_id
group by 1, 2
having min(m.timestamp) < v.created_at - interval '1 day';
```

---

## 9. Archivos tocados

| Archivo | Cambio |
|---|---|
| `src/diana/config/settings.py` | Bandera `feature_vip_history_seed_enabled` (default `false`) |
| `src/diana/composition.py` | Puerta de la bandera + motivo de la desactivación |
| `src/diana/application/vip_history_seed.py` | `disabled_reason`, registro explícito por alta, referencia viva de la tarea |
| `.env` | Comentario de la recarga + bandera nueva con motivo y condición |
| `.env.example` | Bandera nueva documentada |
| `tests/audit/test_C_HIST_01.py` | Prueba E2 + contraprueba (nuevo) |
| `tests/unit/application/test_vip_history_seed.py` | Prueba de la referencia viva de la tarea |
| `faltantes.md` | §7: decisión del 2026-09-06 y condición de reactivación |
| `wiki/entities/specs/estado-del-proyecto.md` | Pendiente registrado con fecha y fuente |
| `audit/contracts/C-HIST-01.md` | Nivel, semáforo y hallazgos actualizados |
| `audit/FASE2-HISTORIAL.md` | Este informe (nuevo) |

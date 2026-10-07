# FASE 2 — Historial: importación desde la cuenta personal

**Contrato:** C-HIST-01 (b) — "El historial previo del VIP se importa desde la cuenta de
Telegram de la dueña, lentamente, un VIP por ciclo".
**Rama:** `audit/historial-decision`. **Fecha:** 2026-10-07.
**Decisión de producto registrada:** 2026-09-06 (cambio de cuenta de Telegram).

---

## 1. Qué se pidió

1. Documentar la decisión del 2026-09-06 con su condición de reactivación y corregir el
   comentario del `.env` que decía "VIVO desde 2026-09-02".
2. Determinar qué hace hoy el alta de un VIP nuevo con la sesión de la cuenta anterior: ¿falla,
   se queda esperando, avisa a la dueña o no hace nada en silencio? ¿Puede bloquear o retrasar
   el alta?
3. Cambio mínimo para que el alta no intente importar con la cuenta anterior y lo diga con un
   registro claro, con prueba E2 y evidencia de sabotaje.

---

## 2. Qué hace hoy el alta de un VIP nuevo (medido, no supuesto)

**Camino real:** `telegram/handlers/admin.py:464` (`/add_vip`) y
`telegram/handlers/menu.py:1422` (confirmación del menú) → `vips.add(...)` →
`VipHistorySeedService.schedule_seed_for_new_vip(...)` → `loop.create_task(...)` →
`_seed_safe` → `seed_for_new_vip` → `TelethonVipHistoryFetcher.fetch_recent`.

| Pregunta | Respuesta | Evidencia |
|---|---|---|
| ¿Bloquea o retrasa el alta? | **No.** El alta se guarda primero y la importación se lanza como tarea de fondo (`create_task`); el handler no la espera. | `vip_history_seed.py:215-218` |
| ¿Falla el alta si la importación falla? | **No.** `_seed_safe` captura cualquier excepción y la convierte en `SeedOutcome(kind="failed")`. | `vip_history_seed.py:227-234` |
| ¿Avisa a la dueña? | **Sí, siempre**, incluso en el caso benigno: el mensaje de "no había historial previo que importar" sale cuando la importación devuelve 0 filas nuevas, y "no se pudo importar" cuando falla. | `vip_history_seed.py:41-61`, `237-246` |
| ¿Se queda esperando? | **Sí, sin límite.** `client.connect()` del fetcher no tiene timeout y el módulo serializa con un `asyncio.Lock` global. Una tarea colgada retiene ese lock. Hoy el lock solo lo usa el propio importador (la recarga está apagada), así que no bloquea ni el alta ni el pipeline. | `vip_history_fetcher.py:147-159` |
| ¿Se intenta de todos modos con la cuenta anterior? | **Sí.** El `fetcher` se construye por configuración presente (`TELETHON_API_ID` + `TELETHON_API_HASH` + `TELETHON_SESSION_PATH`), sin ninguna puerta de producto. El `.env` tiene las tres. | `composition.py:200-234` |

### 2.1 Qué pasó en el único alta real posterior al cambio de cuenta

Registro en producción (`journald`, unidad `diana-bot`):

- Ventana visible: 2026-09-30 → 2026-10-05 (retención de ~7 días).
- `vip_history_seed_enabled` en cada arranque (8 arranques) y
  `history_reimport_job_skipped_flag_off` en cada arranque.
- **Cero** eventos `vip_history_seeded`, `vip_history_seed_empty`, `vip_history_seed_failed` o
  `vip_history_seed_disabled` en toda la ventana: no hubo ninguna alta de VIP en esos días.

Base real (`message_history`, `vips`; consultas de solo lectura):

- 15 VIP registrados. **Uno solo** dado de alta después del 2026-09-06: `Memo L.A.`
  (telegram_user_id 8466399668), alta 2026-09-22, 245 filas de historial, todas con id de
  Telegram, 39 con rol `vip`.
- Orden real de inserción de ese chat (id autoincremental contra la fecha del mensaje):

| Fecha del mensaje | Filas | Rango de id | Roles |
|---|---|---|---|
| 2026-08-09 | 15 | 1689–1703 | owner |
| 2026-08-12 | 2 | 2256–2257 | owner |
| 2026-08-15 | 1 | 2581 | owner |
| 2026-09-08 | 4 | 10992–10996 | owner |
| 2026-09-15 | 59 | 12195–12297 | owner |
| 2026-09-16 | 52 | 12301–12622 | owner |
| 2026-09-17 | 12 | 12652–12665 | owner |
| 2026-09-18 | 19 | 12815–12833 | owner |
| 2026-09-21 | 5 | 13551–13563 | owner |
| 2026-09-22 (alta) | 54 | 13565–13701 | owner, vip |
| 2026-09-23 | 4 | 13708–13718 | owner, vip |
| 2026-09-25 | 14 | 14044–14114 | owner, vip |
| 2026-09-26 | 4 | 14146–14170 | owner, vip |

**Lectura:** el id crece junto con la fecha del mensaje, así que las 18 filas de agosto se
escribieron en agosto (cuando ese chat era de atención general y la dueña escribía allí), no se
importaron en el alta del 22 de septiembre. No existe ninguna fila con fecha anterior al alta e
id posterior al alta, que es la huella que dejaría una importación desde la cuenta anterior. Las
primeras filas con rol `vip` aparecen el mismo 22 de septiembre, o sea que son conversación
nueva de la cuenta en uso.

**Conclusión (probado):** el alta de ese VIP **no trajo historial de la cuenta anterior**.

**Sin determinar (⚪):** no se puede saber si el intento del 22 de septiembre falló
(`vip_history_seed_failed` → aviso "no se pudo importar") o volvió vacío
(`vip_history_seed_empty` → aviso "no había historial previo que importar"). Los registros de esa
fecha quedaron fuera de la retención de `journald` y no se consultó la sesión real a propósito
(ver §6). Pregunta abierta para la dueña: ¿recuerda haber recibido un aviso el 22 de septiembre
al registrar a Memo L.A., y qué decía? Eso define cuál de las dos ramas ocurrió.

---

## 3. Cambio mínimo aplicado

Una sola puerta de producto delante del importador, sin tocar el pipeline ni la memoria.

1. **`Settings.feature_vip_history_seed_enabled: bool = False`** (`config/settings.py`).
   El valor real vive en el `.env` (regla de prioridad de `AGENTS.md` §1).
2. **`composition._build_vip_history_seed`**: el importador solo se construye con la puerta
   encendida **y** credenciales presentes. Con la puerta apagada el servicio se sigue armando
   (los dos puntos de alta no cambian) pero **sin `fetcher`**, así que registrar un VIP nunca
   abre la sesión personal. La configuración de Telethon ya no alcanza por sí sola.
3. **Registro explícito**: `vip_history_seed_disabled_by_flag` al arrancar (con
   `session_path`, si hay credenciales, y el motivo) y `vip_history_seed_skipped_disabled` en
   cada alta, con `telegram_user_id` y `reason="flag_off"`. Apagado a propósito deja de ser
   indistinguible de "no había nada que importar".
4. **Sin aviso a la dueña** cuando la puerta está apagada: no hay ruido por una decisión de
   producto ya tomada.
5. **`.env`** (opción A acordada): se corrigió el comentario "VIVO desde 2026-09-02" de
   `FEATURE_HISTORY_REIMPORT_ENABLED` y se agregó `FEATURE_VIP_HISTORY_SEED_ENABLED=false` con
   motivo y condición de reactivación. Ningún valor de otra bandera cambió.

---

## 4. Prueba E2 y sabotaje

Prueba: `tests/audit/test_C_HIST_01.py`. Entra por el comando real de alta (`/add_vip`) sobre el
contenedor armado por `build_app`, contra Postgres real. Solo se simulan las dos fronteras
externas: la sesión de Telethon y la salida de mensajes a Telegram.

Aserciones de la prueba principal (puerta apagada, credenciales de Telethon presentes):

1. El alta quedó en `vips` (efecto real en la base).
2. `message_history` no recibió ninguna fila para ese chat (no hubo importación).
3. El importador de Telethon **nunca se construyó**.
4. Existen los dos registros con el motivo (`vip_history_seed_disabled_by_flag` al arrancar,
   `vip_history_seed_skipped_disabled` en el alta, con `reason="flag_off"` y el id del VIP).
5. La dueña no recibió ningún aviso.
6. La respuesta del alta sí salió (prueba de que el alta corrió de verdad y no es un no-op).

Contraprueba en la misma suite: con la puerta **encendida**, el importador sí queda cableado
(`test_con_la_bandera_encendida_la_pieza_si_se_cablea`). Sin esta contraprueba, la prueba
principal podría pasar por una pieza rota en lugar de por una puerta cerrada. No se envía ningún
mensaje, así que no se abre ninguna sesión real.

### Sabotaje (E3)

| Sabotaje | Qué se desconectó | Resultado exigido | Resultado obtenido |
|---|---|---|---|
| S1 | La puerta de la bandera en `composition.py` (`if not settings.feature_...` → `if False:`) | La prueba principal debe **fallar** | **Falla** en la aserción 3. Los registros muestran `vip_history_seed_enabled` y `vip_history_seed_empty`: el importador se construyó y el alta lo llamó. |
| S2 | El registro explícito de `schedule_seed_for_new_vip` | La prueba principal debe **fallar** | **Falla** en la aserción 4 (`falta el registro del alta con el motivo`). |

Ambos sabotajes se aplicaron de forma temporal sobre el árbol de trabajo y se revirtieron
inmediatamente; el árbol quedó restaurado (verificado con `grep`).

### Matriz de banderas

| `FEATURE_VIP_HISTORY_SEED_ENABLED` | Efecto en el alta | Evidencia |
|---|---|---|
| `false` (valor actual en `.env`) | No se construye importador, no se toca Telethon, queda registro del motivo, sin aviso a la dueña | **E3** (prueba + S1 + S2) |
| `true` | El importador se cablea; el alta consulta la sesión personal y avisa a la dueña con el resultado | **E2** (se verifica el cableado; la consulta real contra Telegram **no** se ejecutó) |

`FEATURE_HISTORY_REIMPORT_ENABLED` (recarga de VIP existentes) no interviene en el alta: con la
puerta del seed apagada, el servicio de recarga tampoco se construye (`composition.py:1406`).

---

## 5. Archivos tocados

| Archivo | Cambio |
|---|---|
| `src/diana/config/settings.py` | Nueva bandera `feature_vip_history_seed_enabled` (default `false`) |
| `src/diana/composition.py` | Puerta de la bandera + motivo de la desactivación en el armado del importador |
| `src/diana/application/vip_history_seed.py` | `disabled_reason`, registro explícito por alta, motivo en el registro existente |
| `.env` | Comentario de la recarga corregido + bandera nueva con motivo y condición |
| `.env.example` | Bandera nueva documentada |
| `tests/audit/test_C_HIST_01.py` | Prueba E2 + contraprueba (nuevo) |
| `faltantes.md` | §7: decisión del 2026-09-06 y condición de reactivación |
| `wiki/entities/specs/estado-del-proyecto.md` | Pendiente registrado con fecha y fuente |
| `audit/FASE2-HISTORIAL.md` | Este informe (nuevo) |
| `audit/contracts/C-HIST-01.md` | Nivel y semáforo actualizados |

Suites ejecutadas: `tests/audit/test_C_HIST_01.py`, `tests/unit` (4349 pruebas) — todo en verde.

---

## 6. Límites de esta verificación

- **No se consultó la sesión real de Telethon.** Provocar actividad de la cuenta anterior es
  justamente lo que la decisión busca evitar. La frontera de Telethon se simula en la prueba.
- **Sin evidencia de la rama que corrió el 22 de septiembre** (fallo o vacío): los registros de
  esa fecha ya no existen. Queda como pregunta para la dueña.
- **La contraprueba no ejecuta la importación real** (no hay sesión autorizada de la cuenta en
  uso), solo verifica que la pieza se cablea cuando la puerta se enciende.
- Los logs de producción cubren ~7 días; cualquier alta anterior al 2026-09-30 no es observable
  por esa vía.

---

## 7. Pendiente operativo (importante)

El cambio **no está activo en producción**: el proceso en ejecución mantiene el código anterior
cargado. Hasta el próximo reinicio del bot, cada alta de VIP nuevo sigue intentando la
importación con la sesión de la cuenta anterior. No se reinició ni se desplegó nada, según lo
acordado.

---

## 8. Vigilante propuesto (E4)

1. **Alerta si el importador se cablea con la puerta apagada.** Buscar `vip_history_seed_enabled`
   en el arranque mientras `FEATURE_VIP_HISTORY_SEED_ENABLED=false`, o cualquier
   `vip_history_seeded` en operación normal.
2. **Alerta si aparece historial anterior al alta.** Filas de un VIP con fecha de mensaje
   anterior a su fecha de alta son la huella de una importación desde la cuenta anterior:

```sql
select v.telegram_user_id, v.created_at::date as alta, min(m.timestamp)::date as primer_mensaje
from vips v
join message_history m on m.chat_id = v.telegram_user_id
group by 1, 2
having min(m.timestamp) < v.created_at - interval '1 day';
```

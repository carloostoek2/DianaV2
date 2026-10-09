# Fase 2 — Vigilante de contratos (`contract_watchdog`)

**Contratos:** `audit/contracts/C-EMB-01.md` · `C-SHADOW-01.md` · `C-HIST-01.md` · `C-CTX-01.md`
**Código:** `main`. **Fecha:** 2026-10-08. **Corre dentro del bot, en producción.**

---

## Resumen para la dueña

Una prueba en verde dice que el efecto ocurría **el día que se midió**. Si mañana una pieza se
desconecta —una bandera que se apaga, un guardado que vuelve a pisar una columna, el motor de
huellas que devuelve ceros— nada avisa: el producto sigue funcionando y el registro deja de
existir en silencio. **Este vigilante es el que avisa.**

Qué hace, una vez por día, dentro del bot:

- Corre cuatro chequeos sobre la base. **Solo lee: nunca escribe.**
- Si algo falla, te manda **un** mensaje por Telegram. Si está todo bien, **no te escribe nada**.
- El mensaje dice **qué pasó, dónde se nota, desde cuándo y qué hacer**, sin nombres de tablas.
- Incluye los **fallos internos del bot** que hasta ahora no leía nadie.
- Deja su **latido** en `/health`: si dejara de correr, se ve, en vez de parecerse a un vigilante
  tranquilo.

Los cuatro chequeos que corren:

| # | Qué vigila | Contrato |
|---|---|---|
| **V1** | que lo que Diana guarda no quede con la huella vacía (el problema de agosto) | C-EMB-01 |
| **V2** | que cada intercambio con un VIP siga dejando el registro de lo que Diana habría decidido sola | C-SHADOW-01 |
| **V3** | que no quede una escalación sin que la hayas podido resolver | C-SHADOW-01 |
| **V7** | que lo que apruebas o corriges quede guardado (el defecto del 10 de septiembre) | C-SHADOW-01 |

**Lo importante para el negocio:** ninguna de las 16 pruebas es decorativa. Se rompió a propósito
cada condición, una por una (14 sabotajes), y **las 14 pruebas cayeron como debían** (§9).

---

## 1. Dónde vive el job y cómo se planifica

| Pieza | Archivo |
|---|---|
| El job | `src/diana/jobs/contract_watchdog.py` |
| Las decisiones y la copia al usuario | `src/diana/application/contract_watchdog_service.py` |
| Las consultas | `audit/vigilantes.sql` (**fuente única**) |
| El latido | `runtime/contract_watchdog.json` |
| Clasificador de sesiones de prueba | `src/diana/infrastructure/journal_sandbox_turns.py` |

Sigue el patrón de los demás jobs del bot (`CalibrationJob`, `MetricsJob`): un ciclo de una sola
pasada que **nunca propaga excepciones** y una clase que solo lo programa. Se arranca en
`src/diana/main.py` (`_setup_contract_watchdog_job`) y se cancela primero en el `finally` de
apagado, como el resto.

**Cómo se planifica.** Intervalo diario (24 h), con un mínimo de 20 h entre corridas tomado del
latido:

- al arrancar el bot, si el último latido ya tiene 20 h encima, **corre de inmediato**;
- si no, espera lo que falta. Así un reinicio no adelanta el chequeo del día **ni lo corre 24 h
  después** de cada reinicio;
- la espera entre iteraciones nunca baja de 15 minutos: sin ese piso, un latido que no se puede
  escribir dejaría el bucle girando sin descanso contra la base.

**Por qué dentro del bot y no en un proceso aparte.** Los contadores de fallos internos viven en la
memoria del proceso, y `/health` también. Un chequeo en otro proceso no puede leer los primeros ni
publicar el segundo; era justamente lo que le faltaba.

## 2. La bandera

`FEATURE_CONTRACT_WATCHDOG_ENABLED=true` en el `.env` real, con el comentario `VIVO`. En
`Settings` el default es `false` (red de seguridad de un entorno fresco, regla de AGENTS.md §1).
Con la bandera apagada el job no arranca y `/health` responde exactamente igual que antes.

`CONTRACT_WATCHDOG_MIN_HOURS_BETWEEN_RUNS=20` es el mínimo entre corridas.

## 3. El formato del aviso

Así se ve un aviso real (armado con el mismo servicio que lo manda, en modo seco):

```
🔎 Vigilancia Diana — 4 cosa(s) para revisar

• Quedo guardado sin huella (C-EMB-01)
  Que paso: Quedaron registros nuevos guardados sin la huella que permite encontrarlos por
  parecido (el problema de agosto).
  - las fichas de tus VIP: 2 sin huella (antes habia 2)
  Desde cuando: los ultimos 2 dias.
  Que hacer: Avísame: hay que regenerar esas huellas (lo hace el equipo).

• Dejo de registrarse lo que Diana habria decidido sola (C-SHADOW-01)
  Que paso: Dejo de quedar el registro de lo que Diana habria decidido sola.
  - un intercambio del 08/10 03:43
  Desde cuando: los ultimos 2 dias.
  Que hacer: Avísame: sin ese registro no hay con que medir si Diana ya puede contestar sola.

⚠️ No pude revisar: consulta rota a proposito. (UndefinedColumnError)

Fallos internos del bot desde el chequeo anterior:
- Avisos tuyos que no te llegaron: 3
- Lecturas de animo que fallaron: 1

(Descarte 5 intercambio(s) de sesiones de prueba: no se guardan a proposito.)

Detalle tecnico: runtime/contract_watchdog.json
```

Decisiones de la copia:

- **Nunca nombra una tabla.** Donde el chequeo dice `profiles`, el mensaje dice *las fichas de tus
  VIP*; `memories` es *los recuerdos de cada VIP*, `policies` son *las reglas del negocio*,
  `examples` es *lo que Diana aprende de tus correcciones*, `contexts` es *el estado del día de
  cada chat*. Hay una prueba que falla si un nombre de tabla se filtra al aviso.
- **No muestra ids internos.** Cuenta *cuándo* pasó, no la clave del registro.
- Cada bloque responde **qué pasó / desde cuándo / qué hacer**.
- Un vigilante que no se pudo evaluar sale como **"no pude revisar"**, con su motivo: nunca como
  parte de "todo bien".

## 4. Cómo evita repetir el mismo aviso cada día

Tres mecanismos, y ninguno escribe en la base:

1. **Ventana de tiempo en el SQL.** V1 solo cuenta huellas en ceros de los últimos 2 días; V2, V3 y
   V7, intercambios de los últimos 2 días hasta hace 2 horas. Un dato viejo ya conocido no vuelve a
   sonar.
2. **Memoria de lo ya avisado.** El latido guarda la identidad de cada caso avisado (el id del
   intercambio). En la corrida siguiente, ese caso no se repite aunque siga roto. Un caso nuevo,
   sí. Los chequeos que resumen por dato (V1) no tienen identidad propia y se quedan con la
   ventana.
3. **Silencio cuando está todo bien.** Avisar todos los días de "todo bien" entrena a ignorar el
   aviso; por eso el mensaje solo existe si hay algo que revisar.

## 5. Los contadores de fallos internos

El bot se traga fallos a propósito en 46 lugares para no romper un turno (por ejemplo, si el aviso
a la dueña no sale, el turno sigue). Esos fallos quedaban en un contador que **no leía nadie**:
existían en memoria y no se publicaban en ningún lado.

Ahora:

- **entran al aviso**, agrupados en palabras de negocio (*"Avisos tuyos que no te llegaron: 3"*),
  como **delta desde el chequeo anterior** — no el acumulado desde que arrancó el bot;
- se publican **crudos** en `/health`, en `checks.swallowed`, para uso técnico.

Decisión escrita: los contadores **informan, no disparan**. Muchos son benignos por diseño;
disparar por cualquiera convertiría el aviso en ruido diario, que es justo lo que el vigilante
debe evitar.

Límite honesto: si el bot se reinicia, los contadores vuelven a cero y el delta de esa corrida
queda corto. Se reporta lo que hay, sin inventar.

## 6. El latido y `/health`

Cada corrida deja `runtime/contract_watchdog.json` (escritura atómica) con la hora, el resultado,
los casos avisados y la foto de los contadores. `/health` lo lee y publica:

```json
"watchdog": {"ok": true, "enabled": true, "last_run_at": "...", "age_seconds": 320,
             "result": "ok", "alerts": 0}
```

`ok` es `false` si la última corrida **falló** o si el latido tiene más de **36 h** (el chequeo es
diario; 36 h deja margen para un reinicio). En ese caso el estado general de `/health` pasa a
`degraded`. Sin latido previo y con la bandera encendida no se degrada: un arranque recién hecho no
es una falla.

Y si el vigilante **no puede correr**, no se calla: manda el mensaje *"La vigilancia de Diana no
pudo correr"* y deja el latido en `fallo`.

## 7. Calibración de V3 y V6

**V3 — "entregado o escalado sin resolución de la dueña".** Estaba apagado porque la versión cruda
alertaba **por diseño**: hay tres caminos que no dejan resolución registrada y no son fallas.

| Exclusión | Por qué |
|---|---|
| envíos automáticos (`decision.action = 'send'`) | la decisión la tomó el sistema, no la dueña |
| saludos y check-ins de plantilla (`plantilla_saludo`, `plantilla_checkin*`) | responden sin pasar por la cola |
| escalaciones que la dueña ya respondió en el chat | decisión de producto del 2026-10-06 |

Medición contra la base real: **crudo 1 → calibrado 0**, y **0 también en una ventana de 14 días**.
El caso que sobraba era una escalación por riesgo que la dueña ya había respondido en el chat (10
mensajes suyos después de la escalación y ninguno del bot). Con las tres exclusiones **V3 queda
activo**: lo que detecta ahora es una escalación que nadie contestó en ningún lado.

La consulta solo lee rol y hora de los mensajes. **Nunca lee el texto de una conversación.**

**V6 — "VIP activos sin fila de perfil".** Dos hallazgos:

- la consulta estaba **mal escrita**: `profiles` no tiene columna `id`, su clave es **`vip_id`**
  (verificado contra el esquema). Ya está corregida;
- corregida devuelve 12, y ese número **no es una falla**: la ficha de un VIP se crea recién
  cuando la dueña escribe una nota o un dato suyo (`set_fact` / `add_note` en
  `repositories/profiles.py`). "VIP sin ficha" es el estado normal de a quien nunca le anotó nada.

Por eso V6 queda `no-activado`, con el motivo escrito en `audit/vigilantes.sql`. Si algún día
importa saber quién lleva mucho tiempo sin ficha, el chequeo correcto es otro (VIP activo hace N
días sin ninguna ficha), no el conteo crudo.

V4 (entregas sin rastro en el historial) y V5 (recarga de historial detenida) siguen `no-activado`:
el primero pertenece a la ronda de C-HIST-01 y el segundo avisaría de una decisión de producto
(la recarga está apagada a propósito desde el 2026-09-06).

## 8. Pruebas E2 por vigilante

`tests/audit/test_vigilantes.py` — **16 pruebas, todas en verde**, contra Postgres real (contenedor
con la copia de la base). Cada una **siembra el estado malo en la base y corre el servicio real**;
no se asertó "se llamó a tal función".

| Prueba | Qué siembra | Qué exige |
|---|---|---|
| V1 avisa | una huella en ceros recién escrita | V1 aparece con esa tabla en alerta |
| V1 no avisa | una huella en ceros de hace 30 días | esa tabla **no** aparece |
| V2 avisa | turno entregado, con traza, sin registro de sombra | el turno aparece en alerta |
| V2 no avisa | el mismo turno, marcado como sesión de prueba | no aparece, y se informa cuántos se descartaron |
| V2 sin clasificador | — | sale como **"no pude revisar"**, nunca como "todo bien" |
| V3 avisa | escalación con traza y sin resolución, sin respuesta en el chat | el turno aparece en alerta |
| V3 no avisa (×3) | la misma escalación, con plantilla / con autoenvío / con respuesta de la dueña en el chat | no aparece en ninguno de los tres |
| V7 avisa | turno entregado con nota del borrador y sin la decisión | el turno aparece en alerta |
| V7 no avisa | el mismo turno, con la decisión guardada | no aparece |
| Vigilante roto | una consulta rota a propósito | sale como falla y el mensaje dice "no pude revisar" |
| Copia | una alerta real | el mensaje **no** nombra ninguna tabla, y dice qué pasó / desde cuándo / qué hacer |
| Sin nada roto | — | no hay mensaje (silencio) |
| Contrato del SQL | — | los activos son exactamente V1, V2, V3 y V7 |
| El job | un turno sin registro | deja latido, avisa, y **no repite** el mismo caso en la corrida siguiente |

Nota de aislamiento: el contenedor es de sesión y no se limpia por prueba, así que ningún aserto es
global ("no hay alertas de nadie"): cada prueba siembra lo suyo y pregunta por lo suyo (una tabla
para V1, un id de turno para V2/V3/V7).

Más 15 pruebas unitarias en `tests/unit/application/test_contract_watchdog.py` (los contadores en
palabras de negocio, el filtro de lo ya avisado, el latido, el semáforo de `/health`, la guarda de
20 h y el aviso cuando el vigilante no puede correr) y 4 en
`tests/unit/test_vigilantes_script.py`.

Suites completas al cerrar: **4452 unitarias + 233 e2e + 16 de auditoría, en verde.**

## 9. Sabotaje

El arnés vive **fuera del repo** (`/tmp/sabotaje_vigilante/sabote.py`), como en las rondas
anteriores. Cada caso rompe **una** condición con anclas exactas (verificando que el ancla sea
única), corre la prueba que la cubre y exige que **caiga**. Salidas crudas por caso en
`/tmp/sabotaje_vigilante/out/`.

| Sabotaje | Qué se rompió | Prueba que cayó |
|---|---|---|
| V1_ventana_de_2_dias | la ventana de 2 días del chequeo de huellas | `test_v1_no_avisa_por_un_cero_viejo` |
| V2_filtro_de_sandbox | el descarte de turnos de sesiones de prueba | `test_v2_no_avisa_por_un_turno_de_sesion_de_prueba` |
| V2_sin_clasificador_se_calla | el "no pude revisar" cuando falta el clasificador | `test_v2_sin_clasificador_de_sandbox_es_falla_y_no_silencio` |
| consulta_rota_se_traga | el registro de la falla de una consulta rota | `test_un_vigilante_roto_sale_como_no_pude_revisar` |
| V3_exclusion_plantillas | la exclusión de saludos y check-ins | `test_v3_no_avisa_por_un_saludo_de_plantilla` |
| V3_exclusion_autoenvio | la exclusión de envíos automáticos | `test_v3_no_avisa_por_un_envio_automatico` |
| V3_exclusion_duena_respondio | la exclusión de escalaciones ya respondidas en el chat | `test_v3_no_avisa_cuando_la_duena_ya_respondio_en_el_chat` |
| V7_condicion_de_la_duena | la condición de resolución de la dueña | `test_v7_no_avisa_cuando_la_decision_si_quedo` |
| V7_deteccion_desconectada | la detección de V7 (devuelve 0 alertas) | `test_v7_avisa_por_una_decision_no_guardada` |
| no_repite_lo_ya_avisado | el filtro de lo ya avisado | `test_el_job_deja_latido_y_no_repite_lo_ya_avisado` |
| latido_no_se_escribe | el latido | `test_si_el_vigilante_no_puede_correr_igual_avisa` |
| falla_propia_no_avisa | el aviso cuando el vigilante no puede correr | `test_si_el_vigilante_no_puede_correr_igual_avisa` |
| health_ignora_al_vigilante | el semáforo de `/health` | `test_un_vigilante_vencido_deja_el_health_en_degraded` |
| aviso_nombra_tablas | la traducción a lenguaje de negocio | `test_el_aviso_no_nombra_tablas_y_dice_que_hacer` |

**Resultado: 14 sabotajes, 14 mordieron, 0 no.** El árbol quedó limpio y la rama de trabajo se
retiró.

Salida cruda de dos casos:

```
[V1_ventana_de_2_dias]
E       AssertionError: V1 conto un cero de hace 30 dias: el aviso volveria a sonar todos los dias
E       assert 'contexts' not in {'contexts'}

[consulta_rota_se_traga]
>       assert [falla.vigilante_id for falla in report.failures] == ["V9"]
E       AssertionError: assert [] == ['V9']
```

## 10. Límites conocidos

- **El aviso depende de que el bot esté vivo.** Si el bot está caído no hay vigilante; el latido
  vencido se ve en `/health`, pero nadie manda un mensaje. Lo que falta para cerrarlo del todo es
  un vigilante **externo** (un "hombre muerto" en otro servicio) que avise si el bot dejó de
  responder. Queda anotado como pendiente, no como hecho.
- **Un solo vigilante.** El chequeo diario corre dentro del bot y ya no por el reloj del sistema:
  tener los dos serían dos avisos por lo mismo.
- `audit/vigilantes.sql` es leído por código de producción. Es deliberado —una sola verdad entre el
  informe y el chequeo—; la alternativa era moverlo dentro del paquete y dejar el informe apuntando
  a otra ruta.
- El filtro de sesiones de prueba se lee del **journal del bot**. Si el journal no está disponible,
  V2 sale como *"no pude revisar"* (nunca como "todo bien") y los otros tres chequeos siguen
  corriendo.
- El mensaje se corta a 10 renglones por chequeo y resume el resto (*"…y N más"*).

---

## Anexo — reproducir

```bash
# 1. qué avisaría hoy, contra la base real, sin mandar nada
venv/bin/python scripts/vigilantes.py            # mensaje tal como saldría
venv/bin/python scripts/vigilantes.py --json     # resultado crudo por vigilante

# 2. aviso de puesta en marcha (una vez, al activar la vigilancia)
venv/bin/python scripts/vigilantes.py --avisar-activacion --dry-run

# 3. las pruebas E2 por vigilante (Postgres real, contenedor con la copia)
sg docker -c ".venv/bin/python -m pytest tests/audit/test_vigilantes.py -v -p no:randomly"

# 4. las unitarias del vigilante
venv/bin/python -m pytest tests/unit/application/test_contract_watchdog.py tests/unit/test_vigilantes_script.py -q

# 5. el sabotaje (arnés fuera del repo)
python3 /tmp/sabotaje_vigilante/sabote.py
ls /tmp/sabotaje_vigilante/out/                  # salida cruda por caso + informe.json

# 6. el latido y el semáforo en vivo
cat runtime/contract_watchdog.json
curl -s 127.0.0.1:8080/health
journalctl --user -u diana-bot -o cat | grep contract_watchdog
```

# Fase 2 — Aviso de banderas núcleo apagadas al arrancar

**Contrato:** `audit/INVESTIGACION-C.md` §4 (diseño del aviso) · `C-HIST-01`
**Rama:** `audit/aviso-banderas`. **Fecha:** 2026-10-09. Sin commit a `main`, sin despliegue.

---

## Resumen para la dueña

Una bandera apagada solo se veía en el registro técnico, en inglés, en medio de cientos de líneas.
`FEATURE_HISTORY_REIMPORT_ENABLED=false` convivió **un mes** con un comentario que decía lo
contrario, y nadie lo notó hasta una auditoría: los VIP ya registrados nunca completaron su
historial mientras se asumía que ese trabajo corría.

Ahora, cada vez que el bot arranca:

- Deja **un solo resumen legible** en el registro: qué banderas núcleo están apagadas, **con motivo
  y fecha** las que se apagaron a propósito, y en un bloque aparte, marcado como advertencia, las
  que están apagadas **sin declarar**.
- Publica **el mismo resumen en `/health`** (bloque `flags`), sin degradar el estado del sistema.
- Te manda **un mensaje por Telegram**, y **solo si la lista cambió** respecto del arranque
  anterior. Si nada cambió, no te escribe: un aviso que llega en cada reinicio se vuelve ruido.
- **Nunca frena el arranque.** Es un aviso, no un bloqueo.

**Lo que encontró el primer arranque, en la máquina real:**

| Pieza | Estado real | Cómo se ve |
|---|---|---|
| Recarga de historial de VIPs ya existentes | Apagada **a propósito** desde el 6-sep | Bloque de declaradas, con motivo y fecha |
| **Recontacto por silencio** | **Apagada SIN declarar** | **Advertencia** en el registro y mensaje a la dueña |
| Banderas escritas en el entorno que el código no reconoce | Ninguna | Sin novedad |

**Lo importante para el negocio:** la recarga de historial sigue apagada y ahora **se ve por qué**.
El recontacto aparece como un hallazgo real: los VIP que se quedan callados no lo están recibiendo y
no hay ningún motivo anotado. **Hay que decidir** si se declara el apagado (con su motivo) o se
enciende la bandera.

**Lo que NO cambia:** ninguna bandera se encendió ni se apagó. No se tocó el pipeline, ni el
Decisor, ni el motor de comportamiento. El bot no se reinició.

---

## 1. Dónde se declara que una bandera se apagó a propósito

Decisión de producto: la declaración vive en un **archivo versionado del repositorio**,
`src/diana/config/banderas_nucleo.py`. El `.env` real **no está en git**, así que lo que se escriba
ahí no sobrevive a un recambio de máquina ni se revisa junto al código.

Ese archivo tiene dos partes:

- `CATALOGO`: las banderas **núcleo**, cada una con la frase de negocio de qué se pierde si está
  apagada, y —si corresponde— su declaración de apagado (`desde`, `motivo`,
  `condicion_para_reactivar`).
- `FUERA_DEL_CATALOGO`: el resto de las banderas de `Settings`, cada una con el motivo por el que
  no es núcleo.

**Criterio de núcleo:** si la bandera está apagada, algo que el negocio recibe o que la dueña
controla deja de ocurrir. Quedan fuera las que **solo miden** (shadow) y los interruptores que se
apagan a propósito **por seguridad** (envío autónomo, calibración).

Primer caso declarado: `FEATURE_HISTORY_REIMPORT_ENABLED`, desde el 2026-09-06, con el motivo de la
cuenta en uso y la condición para reactivarla.

### Anti-putrefacción

El catálogo clasifica **las 37 banderas** de `Settings`. Una prueba exige que toda bandera nueva
esté en el catálogo o en las exclusiones con motivo: si alguien agrega una bandera y no la
clasifica, la prueba cae. Sin eso, el catálogo se pudre como ya se pudrió la tabla de banderas de
`docs/ARCHITECTURE.md`. Es el equivalente, para el catálogo, de la regla que ya rige para el `.env`:
"un flag ausente es un defecto, no una decisión".

---

## 2. Las tres categorías del resumen

| Categoría | Qué significa | Efecto |
|---|---|---|
| Apagadas **declaradas** | Se apagaron a propósito; hay motivo y fecha escritos | Se muestran con motivo y fecha. **No** generan mensaje |
| Apagadas **sin declarar** | Están apagadas y nadie anotó por qué | **Advertencia** en el registro + mensaje a la dueña |
| **Desconocidas** | Están escritas en el entorno y el código no las reconoce | **Advertencia** + mensaje. Hoy `Settings` las descarta en silencio y el sistema opera como si estuvieran apagadas |

Se reporta además, como nota informativa, una **declaración obsoleta**: una bandera declarada como
apagada que hoy está encendida (la nota quedó vieja). Es exactamente la clase de error que tenía el
`.env.example`.

---

## 3. El registro de arranque

El resumen sale **siempre**, en una sola pieza, desde `main.py` justo después de armar la
aplicación y antes de levantar el servicio y de atender mensajes. Sale siempre porque es la foto
del arranque y el comprobante de que el chequeo corrió; lo que no se repite es el mensaje.

- Con advertencia → nivel **warning** (journald lo destaca).
- Solo con apagadas declaradas → nivel **info**, con el detalle completo (motivo y fecha).
- Sin nada que contar → una sola línea informativa.

Además del texto va el `extra` estructurado (`event=banderas_nucleo`), así que el resumen se puede
buscar en el historial técnico.

---

## 4. `/health`

`build_health_payload` gana un parámetro **opcional** (`flags`), publicado como `checks.flags` solo
si existe — el mismo patrón que ya usan `watchdog` y `swallowed`. Sin el parámetro, la respuesta es
la de antes, así que ninguna prueba existente se toca.

```json
"flags": {
  "ok": false,
  "nucleo_total": 20,
  "apagadas_declaradas": 1,
  "apagadas_sin_declarar": 1,
  "desconocidas": 0,
  "sin_declarar": ["FEATURE_RECONTACT_ENABLED"],
  "nombres_desconocidos": [],
  "declaraciones_obsoletas": []
}
```

**No mueve `status`** a propósito. Una bandera apagada a propósito es una decisión de producto, no
una falla: si degradara el estado, `/health` quedaría en `degraded` para siempre y se aprendería a
ignorarlo, que es justo el problema que se quiere evitar. Quien necesite alertar mira `flags.ok`.

**Aclaración de arquitectura, para no dejar una expectativa falsa:** hoy la vigilancia diaria **no
lee** `/health`, lo **publica** (escribe su latido y `/health` lo muestra). Publicar el resumen ahí
lo deja disponible para quien consulte el estado y habilita que un vigilante lo lea más adelante sin
cambiar nada. Que la vigilancia diaria lo levante por su cuenta es una decisión aparte, y el canal
que se eligió para eso es el mensaje al arrancar.

### El latido

`runtime/banderas_arranque.json`, con escritura atómica (temporal + reemplazo) y `format_version`,
calcado del latido del vigilante de contratos. Se lee del archivo —no de memoria del proceso— para
que `/health` muestre lo mismo que quedó registrado.

Se eligió archivo y no la base por dos razones: el aviso tiene que funcionar **aunque la base no
responda** (de hecho `/health` reporta la base caída por separado), y es un hecho del arranque del
proceso, no un dato de negocio. Es el mismo razonamiento ya escrito en el latido del vigilante.

---

## 5. Pruebas E2 (con el sistema real)

Archivo: `tests/audit/test_banderas_nucleo.py`. Entra por `build_app` (composición real, con el
aviso cableado a Telegram) y por el servidor `/health` **real**, levantado y consultado **por
HTTP**. Lo único simulado es la salida a Telegram: ningún mensaje sale de la máquina.

```bash
sg docker -c "/home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest tests/audit/test_banderas_nucleo.py -v -p no:cacheprovider"
```

| # | Escenario | Qué exige |
|---|---|---|
| E2-a | Bandera núcleo apagada **sin declarar** | Advertencia en el registro, `checks.flags.sin_declarar` la incluye y hay **un** mensaje a la dueña |
| E2-b | La **misma** apagada, **declarada** | Sale como declarada con motivo y fecha; **no** hay advertencia y **no** hay mensaje |
| E2-c | Caso real `FEATURE_HISTORY_REIMPORT_ENABLED` | Aparece como declarada desde el **2026-09-06** |
| E2-d | `/health` con el resumen | Bloque correcto y `status` **sin** degradar |
| E2-d2 | Sin resumen previo | `/health` responde **igual que antes** del cambio |
| E2-e | Dos arranques seguidos, misma lista | **Un solo** mensaje |
| E2-f | Bandera del entorno que el código no conoce | Sale en la tercera categoría y avisa |
| E2-g1 | **Telegram caído** al mandar el mensaje | El resumen queda igual en `/health` y el arranque sigue |
| E2-g2 | **No se puede guardar el latido** | El mensaje a la dueña sale igual |

### Pruebas unitarias (sin Docker)

| Archivo | Qué cubre |
|---|---|
| `tests/unit/test_banderas_nucleo.py` | Comparación pura, huella del aviso y **anti-putrefacción** del catálogo |
| `tests/unit/application/test_aviso_banderas.py` | Lectura del entorno, latido atómico, aviso único, tolerancia a fallos |
| `tests/unit/telegram/test_health_server.py` | Bloque `flags` presente, ausente por defecto y sin degradar el estado |
| `tests/unit/test_main_health_wiring.py` | El resumen sale antes de servir y el bloque llega a `/health` |

**Resultados:** 9 pruebas E2 en verde contra Postgres real, y **4496** pruebas unitarias en verde
(la suite completa, no solo las de esta pieza). El resumen que sigue se midió contra el `.env` real
de la máquina, sin arrancar el bot (ver el anexo).

---

## 6. Sabotaje (E3)

Método: se le arranca a propósito una pieza por vez, se corre **solo** la prueba que debería
delatarlo, y se restaura de inmediato. Si una prueba no cae, es un falso verde y se reporta.

| # | Qué se le arrancó | Prueba que debía caer | Resultado |
|---|---|---|---|
| S1 | La comparación ignora las declaraciones (`declaracion=None`) | declarada no avisa (unit + E2) | **cayeron las 2** |
| S2 | El catálogo se recorre vacío | apagada sin declarar avisa (unit + E2) | **cayeron las 2** |
| S3 | Se quita el bloque `flags` de `/health` | publica el bloque (unit + E2) | **cayeron las 2** |
| S4 | No se compara contra el arranque anterior (avisa siempre) | no repite el aviso (unit + E2) | **cayeron las 2** |
| S5 | Se quita la detección de banderas desconocidas | desconocida avisa (unit + E2) | **cayeron las 2** |
| S6 | Una bandera de `Settings` sin clasificar en el catálogo | **antipudrición** | **cayó** |
| S7 | Se quita la llamada al aviso en `main.py` | el aviso sale antes de servir | **cayó** |

**12 de 12 pruebas nombradas cayeron. Cero falsos verdes.** Nivel de prueba: **E3**.

### Hallazgo del sabotaje, y su arreglo

La prueba E2 que decía cubrir "un fallo no frena el arranque" era **decorativa**: no provocaba
ningún fallo real (el archivo ausente devuelve un conjunto vacío, no un error), así que no caía con
ningún sabotaje. Se reemplazó por dos pruebas que sí ejercen el contrato:

- **E2-g1** — Telegram caído: el resumen queda igual en `/health` y el arranque sigue.
- **E2-g2** — el latido no se puede guardar: el mensaje a la dueña sale igual.

Las dos se verificaron al revés: quitando el manejo de cada fallo, **cada una cae**. El arreglo sale
de haber exigido que toda prueba sea falsable, no de haber confiado en que pasara en verde.

### Límite conocido

La prueba antipudrición exige que **toda** bandera esté clasificada, pero no juzga si la
clasificación es acertada: una bandera nueva podría colocarse en las exclusiones con un motivo
pobre y pasar. Es un límite de criterio, no un falso verde —hoy la prueba cae cuando falta la
clasificación—, y se cubre con revisión humana del archivo, que es corto y legible a propósito.

---

## 7. Retención de logs del servidor (recomendación — no se aplica)

Hoy el registro del servidor solo llega hasta el **30-sep**. Esto es lo que se midió, y lo que
conviene hacer.

### Lo que se midió

| Dato | Valor |
|---|---|
| Configuración activa de journald | **Ninguna**: `/etc/systemd/journald.conf` está todo por defecto; el único ajuste extra es `ForwardToSyslog=yes` |
| Uso actual del journal | **251,8 MB** (usuario 168 MB, sistema 83 MB) |
| Tope de fábrica | ~3,8 GB (10 % del disco de 38 GB, con tope de 4 GB) |
| Ventana retenida | Del **30-sep 01:58 UTC** a hoy: 9 días |
| Arranque actual | 24-sep ~13:23 (14 días de encendido) |
| Volumen real | ~15,8 MB/día entre los dos journals |

**La pérdida no la causó el tope de tamaño:** el uso real está 15 veces por debajo del tope de
fábrica, y `MaxRetentionSec` está en su valor de fábrica (0 = sin límite de tiempo).

**Qué la causó:** el registro más viejo coincide **exactamente** con el inicio del archivo archivado
más antiguo, y faltan ~6 días del mismo arranque. El borrado fue por archivos completos, es decir,
un vaciado. journald **no borra por presión de disco** (deja de escribir), y no hay temporizador,
cron ni regla de logrotate que lo haga: fue un vaciado puntual, manual o de una limpieza externa.

El bot escribe en el **journal de usuario** (`journalctl --user -u diana-bot`), que vive en el mismo
`/var/log/journal/<machine-id>/` y se rige por los mismos ajustes `System*`.

### El ajuste propuesto

Crear `/etc/systemd/journald.conf.d/retention.conf` (requiere `sudo`, por eso no se aplica en este
cambio):

```ini
[Journal]
Storage=persistent
SystemMaxUse=2G
SystemKeepFree=6G
SystemMaxFileSize=200M
MaxRetentionSec=90day
```

Con el volumen medido, 90 días ocupan ~1,4 GB: 2 GB alcanzan con margen. `SystemMaxFileSize=200M`
importa porque el vaciado borra **archivos enteros**: archivos más chicos significan perder menos
historia de golpe. Después: `sudo systemctl restart systemd-journald`.

### Cómo se verifica (todo de lectura)

```bash
systemd-analyze cat-config systemd/journald.conf      # los valores nuevos en efecto
journalctl --disk-usage                               # por debajo del tope
journalctl --list-boots --no-pager                    # debe conservar mas de un arranque
journalctl --user -u diana-bot --no-pager | head -1   # entrada mas vieja retenida
journalctl --verify                                   # integridad
```

Subir la retención **no recupera** lo ya borrado; solo evita que vuelva a pasar.

---

## 8. Hallazgos colaterales

| # | Hallazgo | Acción |
|---|---|---|
| H-B1 | `docs/ARCHITECTURE.md` tiene una tabla de banderas que ya divergió del `.env` real (dice `FEATURE_RECONTACT_ENABLED=true` cuando es `false`, y no lista varias banderas) | Reportado. No se toca en esta rama |
| H-B2 | `.env.example` afirmaba que el seed de historial de un VIP nuevo estaba apagado a propósito desde el 6-sep por la sesión de la cuenta anterior, mientras el `.env` real lo tiene **encendido** y funcionando | **Corregido** en esta rama (solo comentario) |
| H-B3 | `FEATURE_FORCE_PROFILE_WHEN_NOTES` no está en el `.env` real: opera por el default del código, que `AGENTS.md` llama defecto | Reportado. El nuevo resumen lo cubre si alguna vez queda apagada |
| H-B4 | `Settings` carga con `extra="ignore"`: una bandera mal escrita en el `.env` se descarta en silencio y el sistema opera como si estuviera apagada | **Cubierto** por la tercera categoría del resumen |
| H-B5 | `FEATURE_RECONTACT_ENABLED` está apagada sin declarar | **Decisión de producto pendiente** |

---

## 9. Archivos

| Acción | Ruta |
|---|---|
| Nuevo | `src/diana/config/banderas_nucleo.py` |
| Nuevo | `src/diana/application/aviso_banderas.py` |
| Modificado | `src/diana/main.py` (una llamada al arrancar + el latido a `/health`) |
| Modificado | `src/diana/telegram/health.py` (parámetro opcional + `check_flags`) |
| Nuevo | `tests/unit/test_banderas_nucleo.py` |
| Nuevo | `tests/unit/application/test_aviso_banderas.py` |
| Nuevo | `tests/audit/test_banderas_nucleo.py` |
| Modificados | `tests/unit/telegram/test_health_server.py`, `tests/unit/test_main_health_wiring.py` |
| Modificados | `.env.example` y `AGENTS.md` (convención de declaración) |

---

## 10. Garantía de producción intacta

- No se encendió ni se apagó ninguna bandera.
- No se reinició `diana-bot` ni se desplegó nada.
- No se tocó `main`: todo vive en la rama `audit/aviso-banderas`.
- El ajuste de journald **no se aplicó**: queda como recomendación escrita.
- No se cambió el orden de prioridades del Decisor ni ningún flujo cognitivo.

## Anexo — reproducir

```bash
cd /home/ubuntu/repos/DianaV2

# Unitarias (sin Docker)
.venv/bin/python -m pytest \
  tests/unit/test_banderas_nucleo.py \
  tests/unit/application/test_aviso_banderas.py \
  tests/unit/telegram/test_health_server.py \
  tests/unit/test_main_health_wiring.py -q

# E2 contra Postgres real
sg docker -c "/home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest \
  tests/audit/test_banderas_nucleo.py -v -p no:cacheprovider"

# Como sale el resumen contra el .env real de la maquina, sin arrancar el bot
.venv/bin/python -I -c "
import sys; sys.path.insert(0, 'src')
from diana.config.settings import Settings
from diana.config.banderas_nucleo import estado_banderas
from diana.application.aviso_banderas import valores_de_settings, leer_variables_feature
e = estado_banderas(valores_de_settings(Settings()), leer_variables_feature())
print('\n'.join(e.bloque_legible() or [e.resumen_corto()]))
"
```

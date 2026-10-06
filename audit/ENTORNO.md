# Entorno de auditoría — cómo correr las pruebas aquí

Preparado el **2026-10-06** para que la skill `contract-proof` (niveles E2/E3) funcione sin
fricción. Si algo de esto cambia, actualizar este archivo.

## Python

Usar el venv del proyecto: **`.venv/bin/python`** (es el que prioriza `scripts/run_e2e.sh`).
Ya tiene `diana` en modo editable, `pytest`, `pytest-asyncio` y `testcontainers`.

El venv **no tiene `pip`** (fue creado con `uv`). Para instalar algo:

```bash
uv pip install --python .venv/bin/python <paquete>
```

## Docker (obligatorio para E2/E3)

- Docker **29.1.3** instalado y el daemon corriendo por systemd.
- El usuario `ubuntu` fue agregado al grupo `docker` el 2026-10-06. **En una sesión nueva de
  terminal ya no hace falta nada especial.** En una sesión abierta antes de ese cambio, o si
  aparece `permission denied ... /var/run/docker.sock`, envolver el comando con `sg docker`:

```bash
sg docker -c "/home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest tests/e2e -q"
```

- Imagen ya descargada (evita el stall de la primera prueba): `pgvector/pgvector:pg16` (631 MB).
  La levanta `tests/e2e/conftest.py` fixture `pg_container`.

## La base real: se usa una COPIA, nunca la real

La suite completa **crea y borra tablas** (migraciones arriba/abajo) y hace `DELETE` sin
filtro en varias tablas. Correrla contra la base real la dañaría. Por eso las pruebas corren
sobre una **copia local de la base real**:

```bash
./scripts/refresh_e2e_copy.sh     # volcado de solo lectura de la base real → runtime/e2e_copy/
./scripts/run_e2e.sh              # la restaura en el contenedor y corre la suite
```

- La conexión real **sale del `.env`** (`DATABASE_URL`, la misma que usa el bot en producción).
  El script solo lee: `pg_dump` no modifica nada.
- El volcado queda en `runtime/e2e_copy/diana_copy.sql` (ignorado por git). **Contiene datos
  reales de los VIP: no se versiona, no se comparte y no sale de esta máquina.**
- Si la copia no existe, las pruebas corren igual sobre un contenedor vacío con migraciones
  Alembic. **El modo siempre se anuncia en el encabezado de pytest**, así que nunca hay duda de
  qué base se usó:
  - `e2e DB: copia de la base real (diana_copy.sql, 35.6 MB, generada ...)` → datos reales.
  - `e2e DB: contenedor vacío + migraciones Alembic (sin copia ...)` → base vacía.

Variables de control (raras veces necesarias):

| Variable | Para qué |
|---|---|
| `DIANA_E2E_COPY_DUMP` | Usar otro volcado (otra ruta). |
| `DIANA_E2E_COPY_OFF=1` | Ignorar la copia y correr sobre base vacía. |

Verificado el 2026-10-06: la copia cuadra con la base real tabla por tabla (2.443 turnos,
15.682 mensajes de historial, 3.984 ejemplos, los mismos 2 perfiles con embedding en ceros)
y la suite completa da **233 passed** sobre la copia, igual que sobre base vacía.

### La copia no está en `tests/e2e/` por casualidad

Las pruebas de auditoría (`tests/audit/test_<ID>.py`) usan `tests/audit/conftest.py`, que
re-exporta las fixtures de `tests/e2e` (contenedor + copia + `build_app`). Así el Probador
escribe su prueba E2 y ya tiene Postgres real, sin armar nada a mano.

## Comandos útiles

```bash
# Suite completa e2e (tier1/2/3) — el runner maneja venv y grupo docker solo
./scripts/run_e2e.sh

# Subconjunto (lo que usa el agente Probador)
sg docker -c "/home/ubuntu/repos/DianaV2/.venv/bin/python -m pytest tests/audit/test_<ID>.py -q"

# Escaneo estático de cableado (lo usa el agente Rastreador)
.venv/bin/python -I audit/tools/wiring_scan.py . > audit/WIRING_SCAN.md
```

Las pruebas nuevas de la auditoría van en **`tests/audit/`** (ya creada como paquete, con
`__init__.py`, para que pytest no choque con nombres de archivo repetidos).

## Línea base (para no confundir fallos previos con hallazgos)

| Suite | Resultado | Cuándo |
|---|---|---|
| `tests/unit` | 4349 passed (29,7 s) | 2026-10-06 |
| `tests/e2e` completo (base vacía) | 233 passed (29,9 s) | 2026-10-06 |
| `tests/e2e` completo (copia de la base real) | 233 passed (30,4 s) | 2026-10-06 |
| `tests/e2e/tier3/test_app_wiring.py` (Postgres real) | 5 passed (4,2 s) | 2026-10-06 |

Si una prueba que falla ya venía fallando en la línea base, **no es un hallazgo del contrato**:
anotarlo como tal y no contarlo como 🔴.

Tres pruebas asumían una base vacía y se corrigieron el 2026-10-06 para tolerar datos reales
(`test_reimport_cursor`, `test_metrics_atencion_counts`, `test_calibration_data`): verdes en los
dos modos, con las mismas aserciones.

## Límites de este entorno

- **Las pruebas escriben en la copia, no en la base real.** Todo lo que se rompa o se borre
  durante una prueba se recupera volviendo a correr `./scripts/refresh_e2e_copy.sh`.
- Leer la base real **en vivo** (para convertir un riesgo en hecho, como hicieron los contratos
  C-EMB-01 y C-SHADOW-01) es una decisión aparte: la copia es una foto del momento en que se
  generó, y su fecha aparece en el encabezado de pytest. Si la foto es vieja, regenerarla antes
  de concluir nada.
- El `.env` local **sí** existe, así que el Auditor de banderas puede leer los valores de las
  banderas tal como están en esta máquina. Ojo: es el `.env` local, no necesariamente el de
  producción.

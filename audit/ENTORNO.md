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
| `tests/e2e/tier3/test_app_wiring.py` (Postgres real) | 5 passed (4,2 s) | 2026-10-06 |
| `tests/e2e` completo | 233 passed (29,9 s) | 2026-10-06 |

Si una prueba que falla ya venía fallando en la línea base, **no es un hallazgo del contrato**:
anotarlo como tal y no contarlo como 🔴.

## Límites de este entorno

- **No hay credenciales de producción.** Leer la base real (para convertir un riesgo en hecho)
  requiere conexión a Supabase, que no está configurada acá. Los contratos que dependan de eso
  quedan ⚪ y se reportan como "sin verificar", nunca se asumen.
- El `.env` local **sí** existe, así que el Auditor de banderas puede leer los valores de las
  banderas tal como están en esta máquina. Ojo: es el `.env` local, no necesariamente el de
  producción.

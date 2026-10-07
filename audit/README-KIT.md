# Kit de auditoría de contratos — DianaV2

## Qué contiene
- `.claude/skills/contract-proof/` — el método (niveles E0–E4, sabotaje, patrones de prueba).
- `.claude/agents/` — 6 agentes: cartógrafo, rastreador, probador, saboteador, auditor de banderas, árbitro.
- `audit/tools/wiring_scan.py` — escáner estático de cableado.
- `audit/contracts/` — 3 contratos piloto ya trazados.
- `audit/ENTORNO.md` — cómo correr las pruebas aquí (venv, Docker, copia de la base real).
- `audit/LINEA-BASE-E2E.txt` — línea base de la suite e2e.
- `audit/vigilantes.sql` — vigilantes V1–V7 para producción.
- `audit/PILOT-REPORT.md`, `audit/WIRING_SCAN.md`, `audit/INVESTIGACION-A/B/C.md` — resultados y cierre de la primera pasada.

## Instalación (Claude Code, en la raíz del repo DianaV2)
En este repo ya está instalado en su sitio. Para portarlo a otro repo, copia `.claude/`,
`audit/` y `tests/audit/conftest.py` (las fixtures que el probador da por cableadas).
Requiere Docker para las pruebas E2 (testcontainers) y `pip install -e ".[dev]"`.
El entorno concreto de esta máquina está en `audit/ENTORNO.md`.

## Orden de uso por área
1. `cartografo-contratos` → fichas.
2. `rastreador-cableado` + `auditor-banderas` (en paralelo).
3. `probador-efectos` → pruebas en `tests/audit/`.
4. `saboteador` → sin esto no hay verde.
5. `arbitro-reportero` → `audit/REPORTE.md`.

Prompt de arranque sugerido:
> Usa la skill contract-proof. Área: modo sombra. Ejecuta los agentes en orden y entrégame audit/REPORTE.md.

## Regla de oro
Solo E3/E4 es ✅. Sin sabotaje documentado, no hay verde.

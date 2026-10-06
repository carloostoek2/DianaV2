"""Fixtures para las pruebas de auditoría de contratos (skill `contract-proof`).

Las pruebas E2 viven en ``tests/audit/test_<ID>.py`` y deben correr contra
Postgres REAL (nunca contra piezas simuladas) — la misma infraestructura que el
resto de la suite e2e: contenedor pgvector desechable y, si existe, la copia de
la base real restaurada dentro (ver ``audit/ENTORNO.md`` y
``scripts/refresh_e2e_copy.sh``).

Sin este archivo las pruebas de auditoría no verían ninguna de esas fixtures:
pytest solo hereda los conftests de las carpetas padre, y ``tests/audit`` es
hermana de ``tests/e2e``. Se re-exportan tal cual — no se redefinen — para que
exista una sola definición de cada conexión.
"""

from tests.e2e.conftest import (  # noqa: F401  (fixtures re-exportadas para pytest)
    alembic_applied,
    alembic_database_url,
    approve_decision,
    clock,
    consult_doctrine_decision,
    database_url,
    delay_policy,
    engine,
    escalate_decision,
    evaluation,
    fake_actuator,
    make_eval,
    pg_container,
    pytest_report_header,
    send_decision,
    session,
    session_factory,
)
from tests.e2e.tier3.conftest import (  # noqa: F401  (wiring completo por build_app)
    app_container,
    bot,
    dispatcher,
    fake_llm,
    test_settings,
)

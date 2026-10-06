# Patrones de prueba real para DianaV2

Base existente: `tests/e2e/tier1` (flujos), `tier2` (repos SQL), `tier3` (`test_app_wiring`, `test_full_message_flow`). Usan testcontainers + Postgres. Requieren Docker.

## P1 — Entrar por `build_app`
Arma la app con `build_app(settings)` (con las banderas del escenario), no instancies servicios a mano. Si el contrato depende de una bandera, es la prueba de que `composition.py` la entrega.

## P2 — Efecto persistido
Después del flujo, consulta la tabla y asierta valores reales. Ejemplos de "valor de relleno" a rechazar: embedding `NULL`/ceros, `shadow_verdict` vacío, `owner_outcome` sin escribir, historial con 0 filas.

## P3 — Solo el LLM externo es falso
Usa `llm/fake.py` determinista para DeepSeek/Gemini. Embeddings, repos, coordinador, orquestador: reales.

## P4 — Flujo completo del turno
mensaje VIP → pipeline → aprobación/corrección de la dueña → (post-turno) → asertar TODAS las tablas que el contrato promete tocar, no solo la primera.

## P5 — Job real
Para jobs (backfill, reimport, calibración, síntesis, métricas): sembrar datos, ejecutar un ciclo del job real, asertar el efecto y que un segundo ciclo es idempotente.

## P6 — Silencio prohibido
Asertar que, ante fallo inducido (embedder que lanza, tabla bloqueada), el sistema **deja rastro visible** (contador, fila de error, alerta), no solo `logger.info`.

## P7 — Matriz de banderas
Parametrizar con `pytest.mark.parametrize` sobre (bandera ON/OFF) × (efecto esperado). El caso OFF debe asertar "no hay efecto" explícitamente.

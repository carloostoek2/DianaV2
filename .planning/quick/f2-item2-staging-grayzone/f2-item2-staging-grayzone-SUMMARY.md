# SUMMARY: Fase 2 Item 2 — StagingService, GrayZoneService y PolicyDistiller

## Tareas completadas

### Task 1: Contract prerequisites + SQL repos
- **Migration 004**: `alembic/versions/004_vip_frozen_until.py` — adds `frozen_until` (nullable timestamp) to `vips`
- **Vip ORM**: `frozen_until` column on `Vip` model
- **VipRecord**: `frozen_until` field on the application DTO
- **VipStore protocol**: `get_by_id`, `freeze_vip`, `unfreeze_vip` methods
- **SqlVipStore**: all 3 methods implemented; `vip_orm_to_record` includes `frozen_until`
- **Policy domain model**: pure Pydantic `Policy` in `cognitive/models.py` (non-ORM, `ConfigDict(extra="forbid")`)
- **DeliveryContext.is_frozen**: `bool = False` default
- **StagingCandidateRepo**: `insert`, `get_by_id`, `update_status`
- **GrayZoneQueryRepo**: `insert`, `get_by_id`, `update_status`, `expire_older_than`, `list_open`
- **ExamplesRepo.insert**: write method for staging promotion
- **PoliciesRepo.insert**: write method for staging promotion

### Task 2: StagingService + PolicyDistiller
- **StagingService** (`application/staging_service.py`): `save_correction`, `promote_to_example`, `promote_to_policy`, `discard` — all with status validation (`pending` precondition checks)
- **PolicyDistiller** (`cognitive/policy_distiller.py`): `distill_from_text` — mechanical heuristic split, no LLM, returns `cognitive.models.Policy`

### Task 3: GrayZoneService
- **GrayZoneService** (`application/gray_zone_service.py`): `create_query`, `resolve_with_doctrine`, `confirm_and_apply`, `discard_and_close`, `freeze_vip`, `unfreeze_vip`, `expire_old_queries`
- `resolve_with_doctrine` creates StagingCandidate only — does NOT close query or unfreeze (deferred to Item 3)
- `confirm_and_apply`/`discard_and_close` handle lifecycle completion

### Test fix
- `tests/unit/infrastructure/test_sql_repo_shapes.py`: added `frozen_until=None` to `SimpleNamespace` mocks for `vip_orm_to_record` calls

## Commits

| Hash | Message |
|------|---------|
| `e6807eb` | feat(f2): add staging, gray-zone repos, Policy domain model, VipStore freeze, migration 004 |
| `057967c` | feat(f2): add StagingService and PolicyDistiller |
| `54dbc14` | feat(f2): add GrayZoneService with query lifecycle and VIP freeze |
| `d04bba2` | test(infra): add frozen_until to vip_orm_to_record test mocks |

## Desviaciones y resoluciones

| Desviacion | Resolucion |
|------------|------------|
| `examples.py` import de `uuid` duplicado | Eliminado antes de commit |
| `policy_distiller.py` `__all__` duplicado | Eliminado antes de commit |
| Test `test_vip_orm_to_record_mapper` falla por `frozen_until` faltante en mock | Añadido `frozen_until=None` a los 3 `SimpleNamespace` usados con `vip_orm_to_record` |

## Verificaciones corridas

- `alembic upgrade head`: OK
- 6 import checks: OK
- `pytest tests/unit/infrastructure/test_f1_schema_metadata.py`: 11 passed
- `pytest tests/unit/cognitive/test_import_purity.py`: 1 passed
- `pytest tests/unit/cognitive/test_retrievers.py`: 22 passed
- `pytest tests/ -x`: **459 passed**, 0 regresiones

## Self-check: PASSED
- [x] Todas las tareas completadas
- [x] Tests del PLAN corridos
- [x] 0 regresiones atribuibles
- [x] Convenciones del proyecto respetadas

## Residuales
- Ninguno: los hallazgos (`__all__` duplicado, test mock) se corrigieron en el mismo item.

# Escaneo de cableado (estático)

## 1. Funciones sin ningún llamador en src (candidatas a 'no conectadas')

- `application/admin_service.py:264` — `set_gray_zone`
- `application/memory.py:572` — `get_delivery_result`
- `application/memory.py:575` — `seed_keys`
- `application/memory.py:776` — `set_paused_until`
- `application/outcome_log_service.py:414` — `list_outcome_rows_since`
- `application/sandbox.py:251` — `get_context_block`
- `application/turn_coordinator.py:614` — `transition_sink`
- `cognitive/context_builder.py:148` — `list_included_blocks`
- `cognitive/policy_distiller.py:22` — `distill_from_text`
- `cognitive/ports.py:265` — `keys_for`
- `infrastructure/db/repositories/learning_metrics.py:90` — `list_weeks`
- `infrastructure/db/repositories/system_config.py:132` — `get_feature_flags`
- `llm/fake.py:85` — `enqueue_structured`
- `llm/fake.py:82` — `enqueue_text`
- `telegram/handlers/menu.py:188` — `has_active`

Total: 15

## 2. Errores tragados por archivo (`except Exception` / `log_swallowed`)

| Archivo | except Exception | log_swallowed |
|---|---|---|
| application/admin_service.py | 58 | 20 |
| application/turn_orchestrator.py | 41 | 18 |
| telegram/handlers/callbacks.py | 30 | 0 |
| telegram/handlers/doctrine.py | 17 | 0 |
| application/recovery_startup.py | 16 | 0 |
| telegram/handlers/menu.py | 12 | 0 |
| telegram/handlers/persona_admin.py | 11 | 0 |
| composition.py | 9 | 0 |
| telegram/handlers/admin.py | 8 | 0 |
| application/profile_admin_service.py | 7 | 0 |
| application/turn_coordinator.py | 7 | 7 |
| application/recontact_service.py | 7 | 0 |
| infrastructure/vision/ocr.py | 7 | 0 |
| jobs/gray_zone_expiration.py | 6 | 0 |
| application/draft_variants.py | 6 | 0 |

Total except Exception: 385 · log_swallowed: 46
Archivos de producción que leen `get_swallowed_counts`: 0 (NADIE expone los contadores)

## 3. Dependencias que composition.py entrega solo si hay bandera

- `trust_budget` ← `trust_budget_service` solo si `feature_trust_budget`
- `outcome` ← `outcome_log` solo si `feature_autonomy_quality_enabled`
- `memory_extraction` ← `memory_extraction` solo si `feature_memory_enabled`
- `context_store` ← `context_store` solo si `feature_context_enabled`
- `emotional_detector` ← `detector` solo si `feature_emotional_detector_enabled`
- `turn_classifier` ← `classifier` solo si `feature_phatic_autonomy`
- `mood_engine` ← `mood` solo si `feature_mood_engine`
- `trust_budget` ← `trust_budget_service` solo si `feature_trust_budget`
- `outcome_log` ← `outcome_log` solo si `feature_autonomy_quality_enabled`
- `memories` ← `memories_repo` solo si `feature_memory_enabled`
- `trust_budget` ← `trust_budget_service` solo si `feature_trust_budget`
- `severity_counts` ← `turn_outcome_repo` solo si `feature_autonomy_quality_enabled`
- `backfill_queue` ← `backfill_queue` solo si `feature_memory_enabled`
- `memory_approval` ← `memory_approval` solo si `feature_memory_enabled`
- `link` ← `link_coordinator` solo si `feature_link_enabled`
- `emotional_detector` ← `detector` solo si `feature_emotional_detector_enabled`
- `turn_classifier` ← `classifier` solo si `feature_phatic_autonomy`
- `mood_engine` ← `mood` solo si `feature_mood_engine`

## 4. Rutas que se desactivan u omiten solo con un log

- `application/admin_service.py:473` — `gray_zone_delivery_missing_turn` (info)
- `application/admin_service.py:489` — `gray_zone_delivery_missing_bc` (warning)
- `application/admin_service.py:507` — `gray_zone_delivery_missing_turn` (info)
- `application/admin_service.py:1125` — `false_positive_skipped_sandbox` (info)
- `application/admin_service.py:1810` — `escalation_reply_missing_turn` (info)
- `application/admin_service.py:1836` — `escalation_reply_missing_bc` (info)
- `application/admin_service.py:1910` — `owner_escalate_missing_turn` (info)
- `application/admin_service.py:2006` — `admin_resolve_missing_turn` (info)
- `application/admin_service.py:2211` — `owner_history_skipped_sandbox` (info)
- `application/admin_service.py:2327` — `post_turn_skipped_status` (info)
- `application/approval_ui.py:40` — `approval_void_skipped_no_void_draft` (info)
- `application/calibration_service.py:142` — `calibration_skipped_disabled` (info)
- `application/context_store_service.py:71` — `context_store_skipped_no_turn` (debug)
- `application/deterministic_escalate.py:57` — `deterministic_escalation_history_skipped_gate` (info)
- `application/gray_zone_service.py:443` — `gray_zone_query_reopen_skipped` (info)
- `application/memory_backfill_queue.py:169` — `backfill_enqueue_disabled` (info)
- `application/memory_backfill_queue.py:317` — `backfill_missing_enqueued` (info)
- `application/memory_backfill_queue.py:443` — `backfill_job_disabled` (info)
- `application/memory_backfill_service.py:371` — `memory_backfill_disabled` (info)
- `application/memory_backfill_service.py:528` — `memory_backfill_disabled` (info)
- `application/memory_backfill_service.py:570` — `memory_backfill_dedup_skipped` (info)
- `application/memory_extraction_service.py:288` — `memory_extraction_skipped_not_terminal` (info)
- `application/memory_extraction_service.py:296` — `memory_extraction_skipped_not_vip` (info)
- `application/memory_extraction_service.py:408` — `memory_extraction_skipped_no_messages` (info)
- `application/memory_extraction_service.py:521` — `memory_extraction_dedup_skipped` (info)
- `application/promo_service.py:309` — `promo_recovery_missing_trigger_id` (warning)
- `application/recontact_service.py:228` — `recontact_supervised_skipped` (info)
- `application/recontact_service.py:269` — `owner_history_skipped_sandbox` (info)
- `application/staging_service.py:106` — `correction_skipped_sandbox` (info)
- `application/staging_service.py:252` — `gold_example_skipped_sandbox` (info)
- `application/turn_orchestrator.py:422` — `post_turn_skipped_sandbox` (info)
- `application/turn_orchestrator.py:601` — `profile_synthesis_skipped_sandbox` (info)
- `application/turn_orchestrator.py:755` — `mood_skipped_sandbox` (info)
- `application/turn_orchestrator.py:871` — `trust_budget_skipped_sandbox` (info)
- `application/turn_orchestrator.py:1052` — `post_turn_skipped_status` (info)
- `application/turn_orchestrator.py:1251` — `turn_mint_skipped_stale_epoch` (info)
- `application/turn_orchestrator.py:1735` — `vip_history_skipped_sandbox` (info)
- `application/turn_orchestrator.py:1806` — `turn_mint_skipped_stale_epoch_no_prior_turn` (info)
- `application/turn_orchestrator.py:2572` — `phatic_auto_send_disabled` (info)
- `application/turn_orchestrator.py:2830` — `autonomous_disabled_for_vip` (info)
- `application/turn_orchestrator.py:3020` — `owner_history_skipped_sandbox` (info)
- `application/vip_history_seed.py:150` — `vip_history_seed_disabled` (info)
- `cognitive/director.py:540` — `repetition_guard_skipped_by_caller` (info)
- `cognitive/persona_semantic.py:219` — `persona_semantic_shadow_skipped` (info)
- `composition.py:228` — `vip_history_seed_disabled_missing_telethon_config` (info)
- `composition.py:883` — `memory_feature_disabled` (info)
- `composition.py:1704` — `phatic_classifier_thresholds_skipped` (info)
- `composition.py:1730` — `mood_engine_thresholds_skipped` (info)
- `composition.py:1779` — `trust_budget_thresholds_skipped` (info)
- `jobs/metrics.py:160` — `atencion_daily_metrics_skipped_flag_off` (debug)
- `main.py:178` — `embedding_warmup_job_skipped_no_embedder` (info)
- `main.py:192` — `expiration_job_skipped_gray_zone_disabled` (info)
- `main.py:210` — `purge_job_skipped_no_trace_store` (info)
- `main.py:231` — `agent_data_purge_job_skipped_no_stores` (info)
- `main.py:243` — `recontact_job_skipped_flag_off` (info)
- `main.py:260` — `backfill_job_skipped_flag_off` (info)
- `main.py:288` — `history_reimport_job_skipped_flag_off` (info)
- `main.py:308` — `metrics_job_skipped_no_service` (info)
- `main.py:329` — `calibration_job_skipped_flag_off` (info)
- `main.py:345` — `outcome_reaction_job_skipped_flag_off` (info)
- `main.py:376` — `profile_synthesis_job_skipped_flag_off` (info)
- `telegram/handlers/doctrine.py:264` — `doctrine_proposal_missing_rule` (info)
- `telegram/handlers/doctrine.py:388` — `doctrine_escalate_missing_turn` (info)

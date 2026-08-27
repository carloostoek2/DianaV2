# DianaV2 Changelog

Highlights of what's new and fixed in Diana, from her early releases through the latest work.

## Image vision with a local privacy filter — 2026-08-26

### ✨ New Features
- **Diana can see inbound photos** (`FEATURE_IMAGE_VISION_ENABLED`, default OFF): when a VIP sends a photo, Diana gets a short objective caption ("una foto del plato", "una captura de pantalla") and replies based on it. The caption enters the pipeline as plain turn text, so the cognitive core (Analyst → Generator → Evaluator → Decider) is untouched.
- **Local privacy filter before anything leaves the server**: a local OCR reader (tesseract, `infrastructure/vision/ocr.py`) extracts the image text, and owner-approved rules (`application/image_vision_service.py`) flag **credit/debit cards** (13–19 digits with Luhn check / 4-groups / Amex), **invoices and receipts**, **identity documents**, **credentials/access keys** and **bank accounts**. A match — or an unreadable image, or OCR unavailable — means the photo **never goes to Google**: it goes straight to the owner's review marked "⚠️ no analizada por privacidad". Fail-closed by design: when in doubt, privacy wins. The VIP's caption is evaluated too, not just the OCR text.
- **Non-sensitive images are captioned by Gemini** (`llm/gemini_vision.py`, model `gemini-3.6-flash`, key `GEMINI_API_KEY`): short Spanish-neutral caption, 40 words max. Provider failure is fail-open — the plain `[imagen]` tag is kept and the turn never breaks.
- **The photo reaches the owner's approval DM**: `pending_approvals.photo_file_id` (migration **035**) carries the Telegram file_id; the draft DM attaches the photo above the draft (best-effort: a stale file_id never breaks the approval flow).
- **Sensitive images still get a blind draft**: Diana knows it is a sensitive image (not its content), so the owner always receives a photo + draft pair to approve, correct or escalate as usual.
- The image bytes are **never persisted** — only text (caption or the sensitive mark) becomes turn text; nothing feeds memories/examples/profile (anti-contamination).

### ✅ Tests
- 3130 unit tests passing (new `test_gemini_vision.py`, `test_image_vision_service.py`, `test_image_describer.py`, `test_business_vision.py`, approval photo propagation + notifier photo attach + migration 035 mapping; full suite green).

## Gray-zone solution proposals — 2026-08-25

### ✨ New Features
- **System-generated rule proposals for gray zones**: when Diana cannot resolve a gray-zone question (consult_doctrine), the system now prepares a **proposal** (suggested business rule + suggested reply + suggested scope) using a restricted "general context" loan (global policies, global gold examples, persona catalog) — read-only, nothing persists into memories/examples/profile or the base pipeline context. The owner DM shows the **original message clearly labeled as context** first, then the proposal block marked as a suggestion. New `GrayZoneProposalService` (application layer) + `FEATURE_GRAY_ZONE_PROPOSAL_ENABLED` (default OFF; now ON in `.env`).
- **"💡 Usar regla propuesta" button**: an explicit, unambiguous action that adopts the **system-suggested RULE** (never the reply) through the exact same rule → regenerate → approval path as a hand-written rule. Scope choice (🔒 Solo este VIP / 🌍 A todos) still applies before resolve; the classic 📝 Escribir regla and ⚠️ Escalar buttons remain.
- **Proposal persisted on the open query** (migration **033**, columns `proposed_rule` / `proposed_reply` / `proposal_source` on `gray_zone_queries`): the `dp:` callback and freeze reminders can recover and re-send the proposal; audit-only, never a knowledge-bank write.
- **Fail-open by design**: if proposal generation fails or times out, the DM is sent without a proposal (current behavior) — the consult, the freeze and the parachute paths never degrade.
- **Confirmed guarantee**: if regenerating with the accepted rule still returns `consult_doctrine` (the rule could not be applied), the case **returns to gray-zone resolution**: the query stays `open`, the freeze is held, and the owner can retry with another rule, with the proposal, or escalate. The rule is never auto-applied and no failed draft is sent.

### 🐛 Fixes
- **Regen no longer blocks when the Decider escalates by risk/frustration of the original message**: if the rule was applied and a valid draft was generated (action `escalate` with reason `risk_high` / `frustracion_directa`), the regenerated draft now goes to the owner approval queue instead of failing with "La regeneración no produjo un borrador usable". The safety gate remains absolute: a regenerated draft that fails the safety check (`safety_below_threshold`) is still fail-closed (rule deactivated, case returns to gray-zone resolution).

### 🔧 Improvements
- `ExamplesRepo.list_gold_global` (read-only global gold source for proposals); neutral Mexican Spanish across all new proposal copy (AGENTS §0.6).

### ✅ Tests
- 3079 unit tests passing (+ new `test_gray_zone_proposal_service.py`, dp: callback + keyboard + notifier + orchestrator + migration 033 + regen-returns-to-resolution coverage; escalate-by-risk enqueues / escalate-by-safety fail-closed); gray-zone e2e green.

## Vector stores: contexts implemented, memory aligned, profiles real embeddings — 2026-08-21

### ✨ New Features
- **`contexts` table now fulfills its F2 design (REQ-MEM-06)**: the interpreted temporal context store (created in migration 003 but never wired) is now real. New `ContextsRepo` + post-turn `ContextStoreService` persist the chat's interpreted state (`waiting_for_reply_since`, `is_first_message_of_day`, day/time CDMX) with a 384-dim embedding and a TTL (default 24h) after every terminal turn. `ContextRetriever` prefers the non-expired persisted snapshot and falls back to the live derivation (repo failure never breaks a turn). Flag-gated by `FEATURE_CONTEXT_ENABLED` (ON in `.env`); expired rows purged by the existing `AgentDataPurgeJob`.
- **Profiles use their vector column**: `ProfilesRepo` now receives the embedding service — `set_fact`/`add_note`/`delete_fact`/`delete_note` recompute a real content embedding (previously always zeros) and the repo exposes `find_by_similarity` for semantic profile lookup.
- **`FEATURE_MEMORY_ENABLED` aligned**: the flag was already `true` in `.env` (the runtime source of truth) but the `system_config` row seeded by migration 003 still said `false`. Both are now `true` (and `FEATURE_CONTEXT_ENABLED=true` added), matching SPEC-FASE2 §3 ("Fase 2 = true").

### ✅ Tests
- 2972 unit tests passing (new `test_contexts_repo.py`, `test_context_store_service.py`, context/profile/orchestrator coverage).

## Personalized recontact (Fila 3) + gray-zone policy promotion — 2026-08-22

### ✨ New Features
- **Personalized recontact (REE-02/COG-15)**: `RecontactPersonalizer` — a reduced pipeline (no Analyst/Planner) that gathers the VIP's visible memory (sensitive category excluded), recent profile trend and active policies (global + VIP-scoped), and asks the LLM to rewrite the base recontact template with that context: max two sentences, neutral Spanish, never invents data. Fail-soft by contract: any error falls back to the rendered template, so recontact can never break. On by default once wired (config `personalize: false` disables). Verified against production: messages personalized with real VIP data.
- **Gray-zone policy promotion**: doctrine rules from the gray zone now appear in the owner review queue (📋 Cola de revisión) with rule/draft/scope, and promote to a live policy honoring the GAP-11 scope — they no longer sit as orphan candidates. Review-queue texts moved to neutral Spanish.

### ✅ Tests
- 2861 unit tests passing.

## Fila 2: owner control — policy scope, profile history, hot LLM swap — 2026-08-22

### ✨ New Features
- **GAP-11 — Policy scope choice**: when resolving a gray-zone doctrine query (free text or "usar borrador"), the owner now chooses **🔒 Solo este VIP** or **🌍 A todos** before the rule is saved. The scope travels in the staging candidate payload so the eventual promotion scopes the live policy. Atencion queries (no VIP) resolve global directly, unchanged.
- **EA-06 — Profile version history**: the VIP ficha now shows a **📚 Historial de versiones** section (last 5 versions, date + diff summary) from `vip_profile_history`. No migration; flag OFF keeps the ficha byte-identical.
- **ADM-03 — Hot LLM swap**: `HotSwapLLMProvider` re-reads `system_config["llm"]` (model/base_url/api_key) on a 30s TTL and rebuilds the provider without a restart. Owner surface: **⚙️ Configuración → 🤖 Modelo de IA** (view active model, change with a text wizard, reset to default). New `LLM_MODEL` setting (default `deepseek-v4-flash`); no overrides → byte-identical to the base provider.

### ✅ Tests
- 2841 unit tests passing.

## Shadow mode consult section in the owner menu — 2026-08-22

### ✨ New Features
- **🤖 Modo sombra in the owner menu**: a read-only consult section (no notifications) where the owner can check, on demand:
  - **Resumen y umbrales**: measured turns over the last 7 days with daily trend, totals ("would have sent alone", owner corrections), current thresholds (trust 0.90, classifier 0.70) and the would-be autonomous message.
  - **Confianza por VIP**: trust score per (VIP, category) compared to the threshold (✅ cumple / ⏳ en camino), with the "autónomos" (would-have-sent) and correction counters.
  - **Borradores y decisiones**: full-autonomy simulation — every real turn is re-decided with the REAL Decider (same matrix, autonomy switch ON) over the turn's stored evaluation and comprehension. Shows the real decision vs. the would-be autonomous verdict (✅ would have sent alone / ❌ thresholds not met with per-dimension detail safety/doctrine/naturalness vs mins / ❌ escalated by high risk or upset VIP / ❌ pending doctrine), the per-VIP trust gate (how autonomy is "earned" over time), the real generated draft (the same message the owner approves) and the master-switch note. No schema changes: everything is rebuilt from `pipeline_traces` + `turn_category_log`.
- Nothing about the shadow measurement changes: it still records without deciding; the section only reads (`AdminShadowService`).

### 🔧 Improvements
- New repo read methods (`turn_category_log.daily_counts` / `list_would_autonomous` / `list_recent_with_draft`, `vip_trust_budget.list_all`) powering the views. No schema changes: the draft was already persisted in `pipeline_traces.generated_text`.

### ✅ Tests
- 2806 unit tests passing (new `test_admin_shadow_service.py`; root-menu layout tests updated for the new button).

## PII masking at the LLM boundary + production DB verified — 2026-08-22

### ✨ New Features
- **PII masking before every LLM call**: emails, phone numbers (MX and international), payment cards (Luhn-validated), @handles and URLs are replaced with collision-safe placeholders before the payload leaves the system — in every LLM call (analysis, generation, evaluation, memory, profile synthesis). If the model echoes a placeholder, it is restored to the original value on the reply, so the VIP-facing text and stored traces are unchanged. Controlled by `FEATURE_PII_MASKING_ENABLED` (default on, privacy-first).
- **Provider agreement guide**: `docs/ACUERDO-PROVEEDOR-LLM.md` explains what to ask the LLM provider (data location, retention, training opt-out, security, subprocessors, DPA) — the legal layer that complements the technical masking.

### 🔧 Improvements
- **Production DB verified at head 029**: migrations 027 (temporary events), 028 (Lucien link) and 029 (quality feedback) were confirmed applied in the real Supabase database, with live data present (`link_events` 14 rows, gold examples 2). The operational pending item is closed; project state doc updated.

### ✅ Tests
- 2796 unit tests passing (20 new masking tests).

## Minibot test harness, doctrine fix, and doc refresh — 2026-08-21

### ✨ New Features
- **Minibot external test harness**: a companion harness (`minibot`, a Telethon userbot) now runs automated multi-turn tests against Diana's sandbox, simulating different subscriber profiles and grading her replies with an LLM. Tests stay isolated from real memory and data, honor a turn budget and per-profile rubrics, and can run a full dry pipeline without touching Telegram.

### 🐛 Fixes
- Fixed free-text gray-zone doctrine queries from the owner always answering "Módulo de zona gris no disponible": the resolution path now forwards the active doctrine session.

### 🔧 Improvements
- Documentation reorganized from implementation roadmap to system guides: a consolidated architecture reference (`docs/ARCHITECTURE.md`), a product front-page README, and a single pending-items catalog (`faltantes.md`).

## Cognitive greeting and delivery polish — 2026-08-20

### ✨ New Features
- **Paragraph-bubble delivery**: drafts are split into paragraph bubbles (blank-line blocks) before the character-length split, so multi-paragraph replies arrive as natural separate messages instead of one wall of text.
- **Sending progress**: multi-segment deliveries show the owner a live "sending X/Y" progress indicator.
- **Adjust delivery quirks**: typos + autocorrect (*) are now calibrated based on context (emotion, urgency, etc.).

### 🐛 Fixes
- Fixed a startup hang in the memory backfill queue: the has-history check now uses a single cheap count query instead of walking the entire chat history page by page (which stalled the bot at boot against remote databases).

## Cognitive greeting — 2026-08-16

### ✨ New Features
- **Pure-greeting template cut**: when an incoming message is a short, unambiguous greeting, Diana detects it right after the analysis step and answers with a prepared greeting template — without running the full cognitive pipeline.
- **Template delivery through the orchestrator**: template replies flow through the same turn orchestration as normal replies, so they keep the standard delivery behavior (read, typing, send) and remain fully traceable.
- **Phatic auto-send**: short greetings can be delivered without owner approval when the conversation's trust level allows it, with the safety rules of the cognitive pipeline applied before anything is sent.

## Owner control, Lucien link, and quality feedback — 2026-08-16

### ✨ New Features
- **Destacar / Reprender on VIP drafts**: the owner can mark a good reply as gold or send a correction now and later save the lesson for that VIP or for everyone. Attention-channel drafts never show these buttons.
- **Gold-first example bank**: highlighted replies are retrieved before ordinary ones. Lessons can be global or VIP-scoped.
- **Lucien → Diana VIP-kick notice**: when Lucien removes a subscriber, Diana asks the owner to expel, disable, or keep that VIP.
- **Temporary events**: the owner can inject a dated context note (start/end). It reaches the model as short-lived context and never mixes into VIP memory or the example bank.
- **Live delivery feedback**: approving a draft shows seen → typing → sent; regenerate shows “Regenerando…”.
- **Honest stale-button toasts** when Approve/Correct/Escalate no longer apply.
- **VIP name on the owner draft**, inbound media type tags, and free-text doctrine replies.

### 🔧 Improvements
- Owner menu is the primary control surface (slash commands remain as aliases). A1–A13 menu UX items are closed.
- If a VIP doctrine query fails to reach the owner, Diana unfreezes the VIP and sends the draft to approval instead of leaving them stuck.
- Startup recovery handlers run as background tasks and never auto-send.

## Agent evolution (shadow observation) — 2026-08-07

### SHADOW MODE

Durante el entrenamiento, Diana tiene la capacidad de observación en la sombra: mientras la dueña atiende una conversación real, Diana ejecuta en paralelo todo su proceso cognitivo, análisis, generación, evaluación y decisión, sin interferir en la entrega. Al final del turno, el sistema compara lo que Diana habría hecho con lo que la dueña hizo realmente, y esa comparación se convierte en aprendizaje.

Este estado acompaña a la supervisión real para acumular evidencia de cómo decidiría Diana ante cada conversación.

### ✨ New Features
- **Shadow agent-evolution engine**: a complete observational layer now watches how Diana handles each conversation — emotional signals, turn-by-turn self-assessment, mood, and per-VIP trust — and records it all for analysis.
- **Emotional signal detection**: Diana now spots emotional cues in incoming messages with a lightweight local heuristic (no external AI calls).
- **Automatic profile refresh**: when a VIP's conversation shows strong signals, Diana can trigger a profile synthesis on her own, keeping VIP profiles current without a manual action.
- **Turn-by-turn self-classification**: for every turn, Diana records how she would have handled it autonomously and her confidence in that call.
- **Three-axis mood engine**: Diana now tracks her emotional tone across conversations to keep her delivery consistent.
- **Trust budget per VIP**: Diana keeps a running trust score per VIP based on how consistently she handles their conversations, with configurable thresholds and a status card.
- **Correction events**: behavior that needs recalibration is captured as a structured correction event in the trust system.
- **Automatic data housekeeping**: agent-evolution records are purged automatically on a schedule (TTL) so the system stays bounded.

### 🔧 Improvements
- **Hardened shadow layer**: several review rounds fixed event-hook safety, deterministic behavior, database-write guards, and in-flight-turn handling.
- **Live tuning**: shadow behavior can be overridden at runtime per environment without redeploys.
- **Sensitive-content priority**: the classifier weighs sensitive or personal content first when assessing a turn.

## ✨ New Features
- **Automatic memory**: Diana now saves relevant details from conversations (preferences, dates, topics) and recalls them later, without being asked.
- **VIP profiles**: Diana builds a profile for each VIP from their chat history and a dedicated profile action, so preferences stay up to date across the whole bot.
- **Attention channel for non-VIP chats**: a dedicated flow for non-VIP conversations, including a real escalation path where unresolved questions reach the owner with a resolution workflow.
- **VIP freeze and pause**: freeze or unfreeze a VIP (1 day, 1 week, or indefinitely), with reminders when a frozen VIP keeps writing.
- **Redesigned menu**: the VIP profile now offers direct actions, a sandbox activation wizard, back buttons, in-place edits, and registering a VIP simply by forwarding their message.
- **Owner review queue (staging)**: Diana's example replies can be staged and approved or discarded by the owner before they are used.
- **Owner dashboard**: weekly summary and metrics commands (`/resumen`, `/metricas`) with trend tracking, plus a way to flag wrong answers for recalibration.
- **Traceability**: the owner can inspect, step by step, how Diana reasoned through a conversation and how long each step took.
- **Re-engagement for non-VIPs**: when a non-VIP asks for more information, Diana opens a 30-day attention cycle and can schedule follow-up messages.
- **Autonomous follow-ups**: after an initial reply, Diana can send follow-up messages on her own, with natural pacing instead of a single immediate answer.
- **Handles edited messages**: if a VIP edits their message, Diana aborts the in-flight work and restarts with the corrected text.
- **Resilient recovery**: after a restart, Diana picks up missed messages and unfinished turns so nothing is lost.
- **Owner sandbox**: test Diana's behavior in a safe sandbox before enabling real delivery.

## 🔧 Improvements
- **Faster history**: long conversations now load quickly and reliably, even with many messages.
- **More human delivery**: replies are paced with natural delays and typing, varying by mode (supervised vs. autonomous) to match Diana's original cadence.
- **More natural Spanish voice**: Diana now uses neutral Spanish consistently, with an emotion-sensitive tone and no dialect-locked or slang-heavy phrasing.
- **Better conversation flow**: bursts of messages are grouped instead of answered one by one, and repeated questions are recognized and handled better.

## 🐛 Fixes
- Fixed memory summaries repeating old facts instead of showing the most recent ones.
- Fixed history pagination errors in long conversations.
- Fixed a crash when saving a memory without text (the error no longer exposes the raw message).
- Fixed timezone and day-boundary issues so Diana's daily behavior aligns with the Mexico City day.
- Fixed message-loss gaps during recovery after restarts.
- Fixed orphaned approvals and stale timers that could block a VIP's turn.
- Corrected several Spanish accent and wording issues in the interface.

## 🔒 Security
- **Personal data protection**: memory errors and logs no longer expose raw message content; stored facts are kept out of logs with an explicit data disclaimer.
- **Input hardening**: incoming messages are sanitized so they cannot break out of Diana's prompts.
- **Admin access control**: owner-only gates on all admin surfaces, and attention-channel access fails closed on errors.

## ⚠️ Breaking Changes
- The attention channel is now live only for chats that received the promo and stays open for a 30-day cycle (payment closes it). Chats without the promo are not admitted.

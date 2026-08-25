# Product Clarification — Owner Admin, Real VIP Profiles & Sandbox

**Status:** **IMPLEMENTED** (pool `owner-admin-sandbox` closed 2026-07-27) · **menu + UX harden live** (2026-08-12) · **quality feedback gated** (2026-08-16, default OFF)  
**Planning lock:** clarified 2026-07-27 · product rules below remain the source of truth  
**Project:** DianaV2  
**Source:** owner conversation + residual inventory (post `residuals-polish`) + v1 reference repo `../diana`  
**Audience:** product + implementers (hardener / SDD)  
**Pool evidence:** `.planning/quick/owner-admin-sandbox/POOL-SUMMARY.md`

### Implementation map (post-pool)

| Product slice | Pool item | Key surfaces |
|---------------|-----------|--------------|
| Real VIP facts/notes write | item1 profile-write | `profile_content`, `ProfilesRepo` writers, `ProfileAdminService`, `/vip_*`, ContextBuilder fence |
| Real VIP list/rename/remove+purge | item2 vip-crud | `VipStore.list_active`/`rename`, purge on `/remove_vip`, private DM gate |
| Sandbox catalog + session | item3 sandbox-core | `src/diana/config/sandbox_profiles.json` (6 keys), `SandboxService` |
| Sandbox admin + isolation | item4 sandbox-admin | `/sandbox *`, auth bypass, fixture inject, real delivery under session, learning/`should_persist` skip, recontact skip |

Feature flags (defaults **false** unless noted):

| Flag | Default | What it gates |
|---|---|---|
| `FEATURE_SANDBOX_ENABLED` | **false** | Sandbox menu section + `/sandbox *` |
| `FEATURE_QUALITY_FEEDBACK_ENABLED` | **false** | Destacar / Reprender on **VIP drafts only** |
| `FEATURE_PERSONA_ADMIN_ENABLED` | **false** | “Personalidad y reglas” in the owner menu |
| `FEATURE_GRAY_ZONE_ENABLED` | **false** | Doctrine consult DM (`dr:` / `dx:` / `de:`) |
| `FEATURE_STAGING_ENABLED` | **false** | Staging queue (promote / two-step discard) |
| `LLM_THINKING_ENABLED` | **true** | DeepSeek thinking on free-text drafts only (`reasoning_effort=low`; cap-empty retry then thinking-off fallback; short budgets e.g. recontact skip thinking; not a menu button) |

Owner VIP admin (list / add / rename / facts / notes) is always-on (owner + private DM). Slash commands remain as aliases; the **owner menu is the primary surface**.

---

## 1. Global rules (non-negotiable)

| # | Rule |
|---|------|
| G1 | **Owner is the only operator** of subscribers: add, edit, delete, and all administrative actions. No self-serve VIP admin; no automatic promotion of real subscriber data without owner path. |
| G2 | **All admin/ops UX is via Telegram.** The primary surface is the **owner menu** (`/start` or `/menu` → `🌸 Panel de Diana`). Slash commands (`/add_vip`, `/vip_*`, `/sandbox`, `/turnos`, `/fp`, `/resumen`, `/staging`) stay as owner-only aliases. Draft approve/correct/escalate (and gated Destacar/Reprender) live on the draft DM, not in the menu. |
| G3 | **Day-0 may have zero real subscribers.** Real users appear only when the owner adds them. No production seed of real VIP rows is required. |
| G4 | **Sandbox uses configured test profiles** (fixtures), separate from real subscriber lifecycle. |
| G5 | Layer limits in `AGENTS.md` still apply (Director deterministic, Behavior only acts, Learning post-turn only, feature flags for gated surfaces). |
| G6 | **Quality feedback is VIP-scoped and flag-gated.** Destacar / Reprender never appear on atención drafts. With the flag off, Aprobar / Corregir / Escalar is unchanged. Reprender delivers the corrected text immediately; the follow-up combo only promotes the lesson (it does not send again). |

---

## 2. Two different “profiles” (do not mix)

| Kind | Purpose | Storage (decision) | Who manages |
|------|---------|-------------------|-------------|
| **Real VIP profile** | Permanent knowledge about a real subscriber (`knowledge.profile`) | SQL table `profiles` (PK `vip_id`) | Owner only via Telegram admin |
| **Sandbox fixture profile** | Frozen test personas for pipeline rehearsal | **Static catalog** (JSON shipped with the app), loaded at runtime like v1 | Owner selects/activates session; catalog content is product fixtures (versioned in repo) |

**Not the same residual.** Real VIP write path ≠ sandbox fixture seed.

---

## 3. Real VIP — what is editable

### 3.1 Fixed identity (not edited via “profile facts” UI)

Owned by VIP allowlist / VIP record (and similar fixed fields), **not** by free-form profile enrichment:

- Telegram user id  
- Display name (set at add / explicit rename command if product adds one)  
- Subscription / allowlist dates when present  
- Structural flags (`auto_send`, freeze, etc.) via their own admin actions  

### 3.2 Enrichable content (owner-editable)

What the system **learns and notes** over time — the enrichable layer:

| Field group | Meaning | Maps to v1 sandbox shape | Maps to DianaV2 |
|-------------|---------|--------------------------|-----------------|
| **facts** | Structured durable facts (occupation, location, interests, personality, relationship, etc.) | `facts: { key: value }` | `profiles.content` JSON — e.g. `{ "facts": {...}, "notes": [...] }` (schema locked at plan time) |
| **notes** | Dated free-text notes (historical context, **not** model instructions) | `notes: [{ date, text }]` | same under `content.notes` |

**Invariants:**

- Owner can **add / edit / delete** facts and notes for a real VIP.  
- Fixed identity fields are **not** rewritten through the facts/notes editor.  
- Profile **read** path already exists (`ProfileRetriever` REAL). Residual was **owner write UX + repo writers**, not a migration seed of real people.

### 3.3 Real VIP CRUD (owner Telegram)

Must live in the same admin flow (commands now → menu later):

| Action | Intent |
|--------|--------|
| Add subscriber | Allowlist VIP (exists: `/add_vip`) |
| Edit subscriber | Rename / fixed fields as needed + **facts/notes** editor |
| Remove subscriber | Remove from allowlist (+ policy on cascade of knowledge TBD only if legal/ops require) |
| List / inspect | See VIP + profile summary |

---

## 4. Sandbox — reuse v1 fixtures and behavior

### 4.1 Reference implementation

Repo: `/home/ubuntu/repos/diana` (v1)

| Asset | Location / behavior |
|-------|---------------------|
| Service | `services/sandbox.py` — “perfiles congelados sin persistencia” |
| Catalog file | `diana_sandbox_profiles.json` (runtime; gitignored in v1) |
| Fixture fallback (tests) | `tests/unit/test_sandbox_service.py` embeds 6 profiles |
| Commands | `/sandbox on|off`, `perfil`, `perfiles`, `estado`, `reset` (owner admin) |
| Key invariant | `should_persist(chat_id) == False` while sandbox active |

### 4.2 Fixture profile keys (v1 — port to V2 catalog)

| Key | Label (v1) | Role |
|-----|------------|------|
| `nuevo` | Usuario nuevo | Empty facts/notes — cold start |
| `cercano` | VIP cercano | Warm relationship facts + note |
| `distante` | VIP reservado | Formal / reserved personality |
| `intenso` | VIP emocional | Emotional / sensitive context |
| `vip_largo` | VIP largo | Multi-note history |
| `inyeccion_previa` | Fixture adversarial | Prior “injection-like” note for safety rehearsal |

**Decision:** Port these **six** fixtures into DianaV2 as a **versioned catalog** under the installable package (e.g. `src/diana/config/sandbox_profiles.json` or equivalent), adapted to V2 `content` shape (`facts` + `notes`). Do not depend on a machine-local gitignored file for boot.

### 4.3 Sandbox activation UX (V1 parity, V2 packaging)

**Simple on/off + panel:**

| Command (v1 intent → V2) | Behavior |
|--------------------------|----------|
| `/sandbox` | Help + open **sandbox admin panel** text (future: menu section) |
| `/sandbox on <chat_id> [profile]` | Activate sandbox session for that chat; default profile `nuevo` |
| `/sandbox off <chat_id>` | Deactivate; clear session focus |
| `/sandbox perfil <name>` | Switch fixture on last focused sandbox chat |
| `/sandbox perfiles` | List catalog |
| `/sandbox estado` | Active sessions |
| `/sandbox reset` | Clear in-session RAM for focused sandbox chat (history/pending of that test session only) |

Owner-only, fail-closed (same as other admin commands).

**Current (2026-08):** the same actions live under owner `/menu` → **🧪 Modo de prueba** (forward a chat to activate, then pick a fixture). `/sandbox *` remains as the command alias. The section is hidden/no-op when `FEATURE_SANDBOX_ENABLED=false`.

### 4.4 Isolation decision (chosen)

**Option chosen: V1-aligned session isolation + frozen catalog (recommended for V2).**

| Concern | Decision |
|---------|----------|
| Fixture storage | Static JSON catalog in repo (not owner-edited day-to-day) |
| Session state | In-process map `chat_id → profile_key` (+ focus chat), like v1 |
| Persist learning / staging / real profile writes | **Forbidden** while sandbox active for that chat (`should_persist` false) |
| Delivery | Uses configured `global_mode` / `delivery_mode` (**real Telegram** when supervised\|autonomous). Product knowledge isolation is `should_persist=false`, not delivery mode. Global `global_mode=fake_delivery` remains a separate ops mode. |
| Real `profiles` / `vips` tables | **Do not** treat sandbox fixtures as real subscribers; do not pollute production allowlist |
| Traces | May record with explicit `sandbox: true` metadata for owner audit of tests, or skip production learning metrics — plan to pick one; default: **trace allowed with sandbox flag, learning promotion disabled** |
| Feature flag | `FEATURE_SANDBOX_ENABLED` gates the whole surface; off ⇒ commands no-op / unavailable |

**Rejected for v1 of this work:** separate Postgres schema/DB for sandbox (heavier ops). Can revisit if multi-tenant compliance demands it.

Quality feedback follows the same isolation: Destacar / Reprender **deliver** in sandbox but **do not insert** gold examples or promote lessons (`should_persist` false).

### 4.5 How fixtures feed the cognitive pipeline

When a message arrives for a `chat_id` with active sandbox session:

1. Resolve fixture `facts` + `notes` from catalog.  
2. Inject into retrieval/context as the **profile knowledge** for that turn (same *semantic* role as `knowledge.profile`), without requiring a real VIP row.  
3. Run pipeline under sandbox delivery/persist rules.  
4. Owner sees drafts/approvals with a clear **sandbox** marker (v1: “SANDBOX — perfil: …”).

Exact injection point (ContextBuilder vs retriever stub override) is an implementation PLAN detail; product contract is **semantic parity with real profile facts/notes**.

---

## 5. Unified admin flow (same product slice)

One owner-facing **admin system**. The menu is live; commands are aliases.

```
Owner DM (Telegram)
  └── /start | /menu  →  🌸 Panel de Diana
        ├── 👥 Mis VIPs — register / list / ficha (facts+notes+per-item delete) / rename / pause / deactivate
        ├── 💬 Revisar mensajes — pointer to draft buttons; 🚩 marcar falsa alarma
        ├── 🧪 Modo de prueba — on / off / perfiles / estado / reset  (FEATURE_SANDBOX_ENABLED)
        ├── 📊 Métricas y aprendizaje — weekly summary + JSON document export; staging queue
        ├── 🔍 Historial y diagnóstico — recent turns + trace detail (back-to-draft from the approval DM)
        ├── 📅 Eventos temporales — time-bounded owner-injected context
        ├── 🎭 Personalidad y reglas — persona catalog per channel  (FEATURE_PERSONA_ADMIN_ENABLED)
        ├── ⚙️ Configuración — training mode toggle
        └── Draft DMs (not a menu section)
              ├── ✅ Aprobar / ✏️ Corregir / ⚠️ Escalar  (always)
              ├── Destacar / Reprender  (FEATURE_QUALITY_FEEDBACK_ENABLED + VIP only)
              ├── versions + ♻️ Regenerar (live “Regenerando…”)
              ├── 🔍 Traza (returns to this draft) / 📝 Agregar nota (TTL + /cancelar)
              └── live delivery progress on approve: leído → escribiendo → enviado
```

Gray-zone DMs (when `FEATURE_GRAY_ZONE_ENABLED`): **Escribir regla** (`dr:` free-text RULE, 15 min + scope Solo este VIP / A todos) / **Escalar**. No **Usar borrador**. On submit: live policy + same-turn regen → regenerated draft on the approval queue; freeze held until successful send. If the VIP doctrine DM fails to send, the VIP is unfrozen and the turn demotes to a normal approve draft (`vip_doctrine_notify_failed`).

---

## 6. Mapping to prior residuals

| Residual phrase | Resolution under this doc |
|-----------------|---------------------------|
| “Profile writers / seed” | **Real VIP:** owner Telegram write of facts/notes. **Not** a SQL seed of real people. |
| “Sandbox complete UI” | Owner sandbox panel/commands + fixtures + persist/delivery gates. |
| “Are seeds for sandbox?” | **Yes for fixtures** (v1 catalog). **No for real subscribers** (day-0 empty). |
| `SandboxService()` empty wire | Rebuild/align with v1 session model + catalog; optional repo methods only if PLAN needs DB traces. |
| `insert_sandbox` on ProfilesRepo | **Not required** if catalog+session isolation is chosen (this doc). Prefer not writing fake rows into real VIP `profiles` PK space. |
| FakeDelivery vs FEATURE_SANDBOX | Product: sandbox does **not** force `fake_delivery`. Delivery follows configured `global_mode` / `delivery_mode` (real Telegram when supervised\|autonomous). **Operator risk:** `/sandbox on <chat_id>` targets the chat that **receives** messages — use a dedicated test chat, not a real VIP private chat. Flag alone without session is insufficient. |

---

## 7. Non-goals (explicit)

- Multi-replica shared sandbox session store  
- Owner editing the **fixture catalog** live in Telegram (v1 catalog is frozen; change via deploy/config)  
- Auto-creating real VIPs from sandbox sessions  
- Naturalness multi-retry / schedule REAL (other residuals)  
- Full rich FakeDelivery product UX beyond safe non-send (unless already supported by `global_mode`)  
- Retroactive Destacar / Reprender on already-delivered history (via `/traza`) — out of scope for quality-feedback v1  

---

## 8. HOW items (resolved in pool `owner-admin-sandbox`)

| # | HOW question | Resolution (implementation) |
|---|--------------|-------------------------------|
| 1 | Exact JSON schema of `profiles.content` | Locked: `{ "facts": {str: str}, "notes": [{ "date": "YYYY-MM-DD", "text": str }] }` in `diana.profile_content` |
| 2 | Sandbox `pipeline_traces` metadata | Traces still write (reconstructability); optional `sandbox: true` metadata **deferred** OOS; learning promotion disabled via `should_persist` |
| 3 | Cascade on VIP remove | Soft deactivate + **best-effort delete** of `profiles` row only (C1); no memories/examples/policies/recontact cascade; no hard-delete migration |
| 4 | Command language | English tokens matching existing admin (`/add_vip`, `/list_vips`, `/vip_*`, `/sandbox`) |
| 5 | Work-unit split | 4 items: profile-write · vip-crud · sandbox-core · sandbox-admin |

---

## 9. Acceptance (DoD) — met by closed pool

| # | Acceptance | Status |
|---|------------|--------|
| 1 | With **zero** real VIPs, owner can open sandbox panel, activate a fixture, run a test chat path without creating a production subscriber | **met** |
| 2 | Sandbox session **does not** write enrichable learning/staging as if real | **met** |
| 3 | Owner can add a real VIP and edit **facts/notes** only; fixed identity fields remain outside that editor | **met** |
| 4 | Fixture list matches v1 keys (6 profiles) with adapted content | **met** |
| 5 | All actions owner-only via Telegram commands; menu can call the same handlers | **met** (+ private DM gate; menu is now the primary surface) |
| 6 | `FEATURE_SANDBOX_ENABLED=false` hides/no-ops sandbox surface | **met** |

---

## 10. References

- v1 sandbox service: `/home/ubuntu/repos/diana/services/sandbox.py`  
- v1 command surface: `/home/ubuntu/repos/diana/handlers/admin_auth.py` (`_handle_sandbox_command`)  
- v1 fixture shapes: `/home/ubuntu/repos/diana/tests/unit/test_sandbox_service.py`  
- DianaV2 implementation: `src/diana/application/sandbox.py`, `sandbox_knowledge.py`, `profile_admin_service.py`, `profile_content.py`, `src/diana/config/sandbox_profiles.json`, admin `/vip_*` `/list_vips` `/rename_vip` `/sandbox`  
- Owner menu + draft UX: `src/diana/telegram/handlers/menu.py`, `callbacks.py`, `keyboards.py`, `docs/UX.md`  
- Quality feedback: `docs/SPEC-FEEDBACK.md`, `AdminService.handle_mark_gold` / `handle_reprimand`  
- Architecture limits: `AGENTS.md`  
- Pool close: `.planning/quick/owner-admin-sandbox/POOL-SUMMARY.md`  
- Prior residual close: `.planning/quick/residuals-polish/`

---

## 11. Current owner control (2026-08-16) — what landed after the pool

Product-facing, not a second admin app:

- **Display name on drafts.** The approval DM header uses the VIP `display_name` (fallback: `chat_id`).
- **Honest no-ops.** Stale Aprobar / Corregir / Escalar toasts say whether the turn was replaced, already sent, resolved, cancelled, missing, or frozen.
- **Live approve / regen.** Approve edits the same message (read → typing → sent). Regen shows `♻️ Regenerando…` only after the run actually starts.
- **Media inbound tags.** Photos/videos/files arrive as `[imagen]`, `[video]`, `[audio]`, `[voz]`, `[documento]`, `[gif]`, `[sticker]` plus caption, so the model never sees a blank turn.
- **Menu harden (A1–A13).** Note-from-draft has TTL + `/cancelar`. Wizards survive bad input. Callback spinner clears first. Staging discard is two-step. Errors keep a Back button. Expired sessions warn. Metrics export is a document. Ficha can delete notes/facts. Stale VIP buttons redirect to the list.
- **Destacar / Reprender** — see G6. Flag default **OFF**. Gold-first retrieval and `vip_id` visibility on examples/policies are always in the schema (migration `029_feedback_quality`); the buttons are what the flag hides.
- **Doctrine parachute (VIP).** Notify failure unfreezes and demotes to approve; the owner still gets a draft instead of a silent 24h freeze.

**Document owner:** Architecture / Product  
**Next step:** ops gradual enablement of `FEATURE_SANDBOX_ENABLED` and, separately, `FEATURE_QUALITY_FEEDBACK_ENABLED` when the owner wants Destacar/Reprender in production. Do not turn quality feedback on for atención.

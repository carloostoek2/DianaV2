# Ops: single-instance process-local state

Diana runs as **one active bot process**. Several concurrency and safety
controls are intentionally **process-local** (in-memory). They are correct
under that assumption and are **not** multi-replica safe.

Multi-replica / Redis / shared session stores are **out of scope** for this
product slice. Multi-process chat locking remains residual (TurnCoordinator
G.4: Postgres `SELECT … FOR UPDATE` / advisory locks).

## Process-local inventory

| Component | Location | What is local |
|-----------|----------|---------------|
| **Chat locks** | `ChatLockProvider` / `TurnCoordinator` | Per-`chat_id` `asyncio.Lock` map. Serializes turn coordinate + finalize per chat inside one process. |
| **CorrectSessionStore** | `telegram/handlers/callbacks.py` | In-memory FSM: owner awaiting free-text Correct. TTL (default 15 min). **Restart clears** all sessions (owner presses Correct again — expected). |
| **DedupMiddleware** | `telegram/middlewares/dedup.py` | In-memory TTL cache of update / callback ids. Drops Telegram redeliveries in-process only. |
| **RateLimitMiddleware** | `telegram/middlewares/rate_limit.py` | Per-user sliding window in-process. Owner exempt via constructor id. |
| **PersonaCatalogProvider** | `application/persona_catalog_provider.py` | In-process cache of the active persona catalog per channel (panel "Personalidad y reglas"). Invalidated only by saves/restores **in the same process** (`set_on_change`). Consumers: retrievers (persona facts / voice / policy / schedule), Director persona, Analyst catalog temas, gray-zone proposal, delivery mode. |

## Multi-replica consequences (if run anyway)

Without a shared store / lock:

- **Double long-poll / multi-writer risk** — two processes may both receive and act on the same updates.
- **Split Correct sessions** — Correct pressed on process A; free-text lands on process B → silent ignore or wrong session.
- **Weak rate limits / dedup holes** — each process has its own counters and seen-set; limits are not global.
- **Chat lock does not span processes** — concurrent pipelines for the same VIP chat can race.
- **Stale persona catalog** — an owner edit in "Personalidad y reglas" saved through process A invalidates only A's cache; process B keeps serving its cached catalog (old "Datos personales", rules, persona) until it restarts. Scaling out requires a cross-process invalidation (e.g. Postgres `LISTEN/NOTIFY` on `persona_versions`, or a short TTL on the cache). Not implemented on purpose (single instance).

Do **not** treat these as supported multi-replica features. Prefer a single active process (or implement real shared coordination before scaling out).

## Related

- README: ops assumption under “On startup”
- `TurnCoordinator` module docstring — G.4 multi-process residual
- `CorrectSessionStore` docstring — restart-clear / multi-replica out of scope

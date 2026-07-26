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

## Multi-replica consequences (if run anyway)

Without a shared store / lock:

- **Double long-poll / multi-writer risk** — two processes may both receive and act on the same updates.
- **Split Correct sessions** — Correct pressed on process A; free-text lands on process B → silent ignore or wrong session.
- **Weak rate limits / dedup holes** — each process has its own counters and seen-set; limits are not global.
- **Chat lock does not span processes** — concurrent pipelines for the same VIP chat can race.

Do **not** treat these as supported multi-replica features. Prefer a single active process (or implement real shared coordination before scaling out).

## Related

- README: ops assumption under “On startup”
- `TurnCoordinator` module docstring — G.4 multi-process residual
- `CorrectSessionStore` docstring — restart-clear / multi-replica out of scope

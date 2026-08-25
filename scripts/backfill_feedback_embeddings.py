"""Backfill the retrieval fingerprint of lessons written without one.

One-off (2026-08) recovery for the Destacar/Reprender + staging promotion bug
where examples/policies were inserted with a zero embedding, making them
invisible to similarity retrieval.

Owner decision (reviewed 2026-08):
- KEEP + re-embed: 10 examples (corrections #1-4,6,10,13,14 + the 2 gold).
- DISCARD (delete): 6 example rows that were feature-probing data.
- DELETE: the reprimand policy "Ya comiste?" (probe).

Safety: every affected row id is cross-checked against its expected content
prefix; the script aborts if the zero-embedding set differs from the decision
list. All affected rows are backed up to JSON before any write.

Usage: venv/bin/python scripts/backfill_feedback_embeddings.py
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from diana.cognitive.embedding import EmbeddingService

REPO_ROOT = Path(__file__).resolve().parent.parent
ZERO_VEC = "select ('[' || repeat('0,',383) || '0]')::vector"

# id -> (expected turn_text prefix, expected corrected_text prefix)
KEEP_EXAMPLES: dict[str, tuple[str, str]] = {
    "cd323cf7-81b2-4738-920e-2143409e9f82": ("Me podrías mandar el 19 y el 24", "Holis 😁"),
    "4f327fb7-7d51-42dd-8b73-b9d6fde80029": ("Por qué cuenta? La tesis?", "Tésis, servicio"),
    "514c94bc-e136-438d-868c-db481fb7fd96": ("No inventes que padre", "no inventes, ojalá"),
    "c0c5604d-de10-4beb-bade-4cc1fac26593": ("No sabes que gusto me da saber", "ay gracias"),
    "87dc08ca-913b-4ef1-9fce-1d1e423e6189": ("Gracias...por leerme", "Nada que agradecer"),
    "f6556f77-f8e9-4f23-8d86-379664df4d5c": ("Hola como va tu semana", "Holis 😁 gracias"),
    "d4b188ec-4a2e-4596-9dee-d7a2601f3e64": ("Bien tuve que viajar al funeral", "Mi amor 😕"),
    "5496b55e-1e0f-4f53-a887-2e59564b2020": ("Gracias Hermosa y que hace", "Todo jsjsjs"),
    "da4a063a-9d64-4e00-8b37-e9a93d4b3abf": ("Pero a veces se necesita", "Claro que no me molesta"),
    "830e5440-027c-4ada-86ee-0b76d5f734df": ("Si mucho!!!", "Jsjs me alegra"),
}

DISCARD_EXAMPLES: dict[str, tuple[str, str]] = {
    "61bd3729-819e-497f-85a2-b103279e89ed": ("Te aburro un poco", "Auch 😕"),
    "f875414e-e613-4d65-a987-9044b84abede": ("Que cosas amor? Cuéntame", "Pues entre los niños"),
    "b5a20529-25f1-4ed6-971d-3b9a0dcfabf4": ("Como estas?", "Jshshs si"),
    "87950745-75d0-4985-993a-ff80c339e3fa": ("Pues la verdad es que nunca", "Lo sé y pues así como"),
    "70e642ce-00bc-41a8-9643-527ca660d0e5": ("Please 🙏🏼", "Sí pues será cuestión"),
    "09761b0d-7ccb-41e6-8e3e-72eb571c99c4": ("Hola hermosa buen dia", "Holis 😁"),
}

DELETE_POLICY: dict[str, str] = {
    "14ad742d-e193-4650-a4b1-bed2030b391a": "Ya comiste?",
}


def _load_database_url() -> str:
    env_file = REPO_ROOT / ".env"
    m = re.search(
        r"^DATABASE_URL=(.+)$", env_file.read_text(), re.M
    )
    if not m:
        raise SystemExit("DATABASE_URL not found in .env")
    return m.group(1).strip().strip('"').strip("'")


def _verify(row_id: str, turn: str, corrected: str, expected: dict[str, tuple[str, str]]) -> None:
    exp_turn, exp_corr = expected[row_id]
    if not turn.startswith(exp_turn) or not corrected.startswith(exp_corr):
        raise SystemExit(
            f"CONTENT MISMATCH for {row_id}: expected turn~{exp_turn!r} corr~{exp_corr!r} "
            f"but got turn={turn!r} corr={corrected!r}. Aborting."
        )


async def main() -> None:
    url = _load_database_url()
    engine = create_async_engine(url)
    embedder = EmbeddingService()

    async with engine.connect() as conn:
        zero_examples = (
            await conn.exec_driver_sql(
                f"select id, turn_text, corrected_text from examples where embedding = ({ZERO_VEC})"
            )
        ).all()
        zero_policies = (
            await conn.exec_driver_sql(
                f"select id, trigger_description from policies where embedding = ({ZERO_VEC})"
            )
        ).all()

        by_id = {str(r[0]): (str(r[1] or ""), str(r[2] or "")) for r in zero_examples}
        found = set(by_id)
        expected = set(KEEP_EXAMPLES) | set(DISCARD_EXAMPLES)
        if found != expected:
            raise SystemExit(
                f"ZERO-EMBEDDING SET MISMATCH: found {len(found)} rows, expected {len(expected)}. "
                f"missing={sorted(expected - found)} extra={sorted(found - expected)}. Aborting."
            )
        for rid in KEEP_EXAMPLES:
            _verify(rid, *by_id[rid], KEEP_EXAMPLES)
        for rid in DISCARD_EXAMPLES:
            _verify(rid, *by_id[rid], DISCARD_EXAMPLES)

        pol_by_id = {str(p[0]): str(p[1]) for p in zero_policies}
        if set(pol_by_id) != set(DELETE_POLICY):
            raise SystemExit(
                f"POLICY SET MISMATCH: found {set(pol_by_id)}, expected {set(DELETE_POLICY)}. Aborting."
            )
        for pid, trigger in pol_by_id.items():
            if not trigger.startswith(DELETE_POLICY[pid]):
                raise SystemExit(f"POLICY CONTENT MISMATCH for {pid}: {trigger!r}. Aborting.")

        # Backup everything before any write.
        backup = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "deleted_examples": [
                {"id": rid, "turn": by_id[rid][0], "corrected": by_id[rid][1]}
                for rid in sorted(DISCARD_EXAMPLES)
            ],
            "deleted_policy": [{"id": pid, "trigger": trig} for pid, trig in pol_by_id.items()],
            "reembedded_examples": [
                {"id": rid, "turn": by_id[rid][0], "corrected": by_id[rid][1]}
                for rid in sorted(KEEP_EXAMPLES)
            ],
        }
        backup_path = REPO_ROOT / "scripts" / "backup_feedback_embeddings_2026-08.json"
        backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=1))
        print(f"backup -> {backup_path}")

        # 1) Delete probe rows (ids are validated UUIDs from the DB — safe literals).
        if DISCARD_EXAMPLES:
            ids = "','".join(sorted(DISCARD_EXAMPLES))
            await conn.exec_driver_sql(
                f"delete from examples where id in ('{ids}')",
            )
            print(f"deleted {len(DISCARD_EXAMPLES)} probe examples")
        if DELETE_POLICY:
            ids = "','".join(sorted(DELETE_POLICY))
            await conn.exec_driver_sql(
                f"delete from policies where id in ('{ids}')",
            )
            print(f"deleted {len(DELETE_POLICY)} probe policy")

        # 2) Re-embed kept examples (same anchor as StagingService: turn_text first).
        for rid in sorted(KEEP_EXAMPLES):
            turn, corrected = by_id[rid]
            anchor = turn or corrected
            vec = await embedder.embed(anchor)
            vec_str = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
            await conn.exec_driver_sql(
                f"update examples set embedding = '{vec_str}'::vector where id = '{rid}'"
            )
            print(f"re-embedded {rid} (dims={len(vec)}, anchor_len={len(anchor)})")

        await conn.commit()

        # 3) Verify: each kept example must retrieve itself now.
        for rid in sorted(KEEP_EXAMPLES):
            row = (
                await conn.exec_driver_sql(
                    f"select id, embedding from examples where id = '{rid}'"
                )
            ).first()
            vec = json.loads(str(row[1]))
            self_vec = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
            hit = (
                await conn.exec_driver_sql(
                    f"select count(*) from examples where id = '{rid}' and "
                    f"embedding <=> '{self_vec}'::vector < 1.0"
                )
            ).scalar()
            ok = "SELF-RETRIEVABLE" if hit else "STILL MISSING"
            print(f"verify {rid}: {ok}")

    await engine.dispose()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())

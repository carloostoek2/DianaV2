"""Regenerate the profile fingerprints (`profiles.embedding`) left as zeros.

Two VIP fichas (rows created 2026-07-28 and 2026-07-29) carry the all-zero
vector: they were written *before* the fingerprint engine existed (commit
`fe0a7d7`, 2026-08-23), when every ficha was stored as zeros by design. Nothing
reads those vectors today — the profile reader goes by `vip_id`, and the
similarity helper was removed on 2026-10-07 (see `audit/FASE2-PERFILES.md`) —
so this is a one-time tidy-up of an incorrect datum, not a repair of a live
failure.

Safety model:

* **Simulation by default.** Without ``--apply`` the script only reports what it
  would do and writes nothing.
* **Backup before any write.** All affected rows (full columns, including
  ``content`` and the current vector) are dumped to JSON first. The file goes to
  ``runtime/`` — gitignored — because a ficha is real VIP data and must not be
  versioned.
* **Explicit ``--apply``** for the write, with the target host/database printed
  in a banner.
* **Idempotent.** Once the zeros are gone, a second run reports "0 filas en
  ceros" and exits 0 without writing.
* Only the ``embedding`` column is touched; ``content``, ``tipo`` and the
  timestamps are left alone.

Usage::

    # 1. Simulation (reads DATABASE_URL from .env, writes nothing)
    .venv/bin/python scripts/regenerate_profile_embeddings.py

    # 2. Apply (backup first, then re-embed)
    .venv/bin/python scripts/regenerate_profile_embeddings.py --apply

    # Against another database (e.g. the test copy)
    .venv/bin/python scripts/regenerate_profile_embeddings.py \\
        --database-url "postgresql+asyncpg://user:pass@host:port/db"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from diana.cognitive.embedding import EmbeddingService
from diana.infrastructure.db.repositories.profiles import _content_to_embedding_text

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_DIR = REPO_ROOT / "runtime"

# Same expression audit/vigilantes.sql (V1) uses to count zero fingerprints, so
# "what the watcher alerts on" and "what this script repairs" are the same set.
ZERO_VEC_SQL = "('[' || repeat('0,',383) || '0]')::vector"

_SELECT_ZEROS = sa.text(
    f"select vip_id, tipo, content, created_at, updated_at, embedding::text "
    f"from profiles where embedding = {ZERO_VEC_SQL} order by created_at"
)
_UPDATE_EMBEDDING = sa.text(
    "update profiles set embedding = cast(:vec as vector) "
    "where vip_id = cast(:vip as uuid)"
)


def _load_database_url() -> str:
    """Read DATABASE_URL from the repo .env (same parser as the 2026-08 script)."""
    env_file = REPO_ROOT / ".env"
    m = re.search(r"^DATABASE_URL=(.+)$", env_file.read_text(), re.M)
    if not m:
        raise SystemExit("DATABASE_URL not found in .env")
    return m.group(1).strip().strip('"').strip("'")


def _resolve_database_url(cli_value: str | None) -> str:
    """CLI flag wins, then the environment, then the .env file."""
    if cli_value:
        return cli_value
    from_env = os.environ.get("DATABASE_URL", "").strip()
    return from_env or _load_database_url()


def _target_banner(url: str) -> str:
    """Describe the destination without echoing credentials."""
    parsed = sa.engine.make_url(url)
    return f"{parsed.host}:{parsed.port}/{parsed.database}"


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def _blob_length(content: object) -> int:
    """Characters that would be fed to the engine for this content."""
    if not isinstance(content, dict):
        return 0
    return len(_content_to_embedding_text(content).strip())


def _row_backup(row: object) -> dict:
    """Serializable snapshot of one row (JSON-safe: datetimes → ISO strings)."""
    (
        vip_id, tipo, content, created_at, updated_at, embedding_text
    ) = row  # type: ignore[misc]
    return {
        "vip_id": str(vip_id),
        "tipo": tipo,
        "content": content,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "embedding_before": embedding_text,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the profile fingerprints (profiles.embedding) that are "
            "stored as the all-zero vector. Simulation by default."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the new fingerprints (default: simulation only).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Target database. Defaults to $DATABASE_URL, else the repo .env.",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(DEFAULT_BACKUP_DIR),
        help=f"Where the pre-write backup JSON goes (default: {DEFAULT_BACKUP_DIR}).",
    )
    args = parser.parse_args()

    url = _resolve_database_url(args.database_url)
    target = _target_banner(url)
    mode = "APLICAR (escribe)" if args.apply else "SIMULACIÓN (no escribe nada)"
    print(f"modo: {mode}")
    print(f"base: {target}")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(_SELECT_ZEROS)).all()

            if not rows:
                print("0 filas en ceros — nada que hacer.")
                return

            print(f"{len(rows)} fila(s) con la huella en ceros:")
            # (vip_id as str for SQL, the text to embed)
            pending: list[tuple[str, str]] = []
            skipped: list[str] = []
            for row in rows:
                vip_id = str(row[0])
                text = (
                    _content_to_embedding_text(row[2])
                    if isinstance(row[2], dict)
                    else ""
                ).strip()
                print(
                    f"  - {vip_id} | contenido: {_blob_length(row[2])} caracteres "
                    f"| creada: {row[3]}"
                )
                if not text:
                    skipped.append(vip_id)
                    print("      omitida: la ficha no tiene texto que convertir")
                    continue
                pending.append((vip_id, text))

            if not args.apply:
                print(
                    f"\nSimulación: se regenerarían {len(pending)} huella(s)"
                    + (f", {len(skipped)} omitida(s)" if skipped else "")
                    + ". No se escribió nada."
                )
                print("Para aplicarlo: use --apply")
                return

            # ---- backup before any write -------------------------------
            backup_dir = Path(args.backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
            backup_path = backup_dir / f"backup_profile_embeddings_{stamp}.json"
            backup = {
                "exported_at": datetime.now(UTC).isoformat(),
                "database": target,
                "rows_with_zero_embedding": [_row_backup(r) for r in rows],
                "regenerated": [vip for vip, _ in pending],
                "skipped_no_text": skipped,
            }
            backup_path.write_text(
                json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"\nrespaldo -> {backup_path}")

            # ---- re-embed with the same engine the system uses ---------
            embedder = EmbeddingService()
            written = 0
            for vip_id, text in pending:
                vec = await embedder.embed(text)
                await conn.execute(
                    _UPDATE_EMBEDDING,
                    {"vec": _vector_literal(vec), "vip": vip_id},
                )
                written += 1
                print(f"  regenerada {vip_id} (dims={len(vec)})")
            await conn.commit()

            # ---- verify: nobody should still be at zero ----------------
            left = (await conn.execute(_SELECT_ZEROS)).all()
            for vip_id, _text in pending:
                check = (
                    await conn.execute(
                        sa.text(
                            "select embedding::text from profiles "
                            "where vip_id = cast(:vip as uuid)"
                        ),
                        {"vip": vip_id},
                    )
                ).scalar_one()
                non_zero = any(abs(float(x)) > 0.0 for x in json.loads(check))
                print(
                    f"verify {vip_id}: "
                    + ("HUELLA REAL" if non_zero else "SIGUE EN CEROS")
                )

            print(
                f"\nlisto: {written} huella(s) regenerada(s); "
                f"quedan {len(left)} fila(s) en ceros."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

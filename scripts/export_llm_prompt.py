"""Export the EXACT LLM payload for a turn, reconstructed from the trace DB.

The trace store (pipeline_traces.prompt_text) keeps the user-message content
verbatim — that is exactly the string passed to the Generator. The system
message is a code constant (_SYSTEM in diana.cognitive.generator), NOT stored
per turn; this script reconstructs it from git at the turn's timestamp for
fidelity and warns when it must fall back to the current HEAD constant.

Usage:
    python scripts/export_llm_prompt.py [turn_id] [--out PATH]

Without turn_id it picks a random turn with a non-null prompt_text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env"
DEFAULT_OUT = REPO / "docs" / "prompt-llm-turno-{short}.md"

_GENERATOR_REL = "src/diana/cognitive/generator.py"


def _load_db_url() -> str:
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().replace(
                "postgresql+asyncpg://", "postgresql://"
            )
    raise SystemExit("DATABASE_URL not found in .env")


def _system_prompt_at(commit: str) -> str | None:
    """Evaluate the ``_SYSTEM`` constant of generator.py at a git commit.

    Uses ``ast`` instead of regex so tuple concatenation like
    ``"..." + _HARD_BAN_RULE + "..."`` resolves correctly (implicit string
    joins and ``+`` of module-level string constants).
    """
    import ast

    try:
        blob = subprocess.run(
            ["git", "show", f"{commit}:{_GENERATOR_REL}"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    tree = ast.parse(blob)
    assignments: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value

    def _eval(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return _eval(assignments[node.id]) if node.id in assignments else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = _eval(node.left), _eval(node.right)
            return left + right if left is not None and right is not None else None
        if isinstance(node, ast.Tuple):
            parts = [_eval(e) for e in node.elts]
            if any(p is None for p in parts):
                return None
            return "".join(parts)
        return None

    return _eval(assignments.get("_SYSTEM")) if "_SYSTEM" in assignments else None


def _commit_active_at(ts: datetime) -> str:
    """Commit on diana/cognitive/generator.py that was HEAD at ``ts``."""
    out = subprocess.run(
        [
            "git", "log", "-1", "--before", ts.isoformat(),
            "--format=%H", "--", _GENERATOR_REL,
        ],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return out or "HEAD"


async def fetch_turn(conn, turn_id: str | None) -> dict:
    if turn_id:
        rows = await conn.fetch(
            """
            SELECT pt.turn_id, pt.chat_id, pt.channel_type, pt.created_at,
                   pt.prompt_text, pt.generated_text, pt.comprehension,
                   pt.decision, pt.timings, t.status
            FROM pipeline_traces pt
            LEFT JOIN turns t ON pt.turn_id = t.id
            WHERE pt.turn_id = $1
            """,
            UUID(turn_id),
        )
    else:
        rows = await conn.fetch(
            """
            SELECT pt.turn_id, pt.chat_id, pt.channel_type, pt.created_at,
                   pt.prompt_text, pt.generated_text, pt.comprehension,
                   pt.decision, pt.timings, t.status
            FROM pipeline_traces pt
            LEFT JOIN turns t ON pt.turn_id = t.id
            WHERE pt.prompt_text IS NOT NULL AND length(pt.prompt_text) > 50
            ORDER BY random()
            LIMIT 1
            """
        )
    if not rows:
        raise SystemExit("No trace found")
    return dict(rows[0])


def _as_obj(value):
    """asyncpg may return JSONB as str; coerce to dict/list for convenience."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def build_doc(turn: dict, system: str, sys_commit: str, sys_fallback: bool) -> str:
    prompt = turn["prompt_text"]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    timings = _as_obj(turn.get("timings")) or {}
    decision = _as_obj(turn.get("decision")) or {}
    redraft = timings.get("naturalness_redraft") is not None
    created = turn["created_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
    short = str(turn["turn_id"])[:8]

    lines: list[str] = []
    add = lines.append
    add(f"# Payload exacto al LLM — turno `{short}`")
    add("")
    add("| Campo | Valor |")
    add("| --- | --- |")
    add(f"| turn_id | `{turn['turn_id']}` |")
    add(f"| chat_id | `{turn['chat_id']}` |")
    add(f"| channel | `{turn['channel_type']}` |")
    add(f"| created_at | `{created}` |")
    add(f"| status | `{turn.get('status') or 'N/A'}` |")
    action = decision.get("action", "N/A")
    add(f"| decision | `{action}` |")
    add(f"| naturalness_redraft | `{redraft}` |")
    add("")
    if sys_fallback:
        add(
            "> ⚠️ El system prompt es una constante de código (`_SYSTEM` en "
            "`generator.py`), no se guarda por turno. No se pudo resolver el "
            "commit activo en la fecha del turno; se usó el de **HEAD**."
        )
    else:
        add(
            f"> El system prompt es una constante de código (`_SYSTEM`), no se "
            f"guarda por turno. Se reconstruyó desde el commit activo en la "
            f"fecha del turno: **`{sys_commit[:7]}`**."
        )
    add("")
    add("## Llamada al LLM (arreglo `messages`, orden exacto)")
    add("")
    add("```json")
    add(json.dumps(messages, ensure_ascii=False, indent=2))
    add("```")
    add("")

    # Section map of the user prompt (variables + order).
    add("## Estructura del mensaje de usuario (`prompt_text`)")
    add("")
    add("El mensaje de usuario es **una sola cadena**; estas son las secciones")
    add("que la arma `ContextBuilder.build()` en orden:")
    add("")
    order = (
        ("`## Persona`", "persona (catálogo vivo o fallback del boot)"),
        ("reglas de estilo", "`style_rules` (una línea por regla, tras Persona)"),
        ("`## Knowledge: …`", "bloques en orden fijo D.4: history, context, persona_facts, voice_patterns, memory, policy, examples, schedule, profile — solo los no-nulos"),
        ("`## Comprehension`", "intent, topics, emotion, urgency, risk"),
        ("`## Current VIP message`", "el texto del VIP (`turn.text`), última sección"),
    )
    for heading, source in order:
        add(f"- {heading} — {source}")
    add("")
    if redraft:
        add("> Hubo redraft de naturalness: el LLM recibió una SEGUNDA llamada")
        add("> con `prompt_text` + recordatorio `--- REDRAFT ---` (mismo system).")
        add("")

    add("## Borrador generado (`generated_text`)")
    add("")
    add("```")
    add((turn.get("generated_text") or "").strip())
    add("```")
    add("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("turn_id", nargs="?", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    conn = await asyncpg.connect(_load_db_url())
    try:
        turn = await fetch_turn(conn, args.turn_id)
    finally:
        await conn.close()

    sys_commit = _commit_active_at(turn["created_at"])
    sys_fallback = False
    system = _system_prompt_at(sys_commit) if sys_commit != "HEAD" else None
    if system is None:
        sys_fallback = True
        sys_commit = "HEAD"
        system = _system_prompt_at("HEAD")
    if system is None:
        raise SystemExit("Could not resolve _SYSTEM")

    short = str(turn["turn_id"])[:8]
    out = Path(args.out) if args.out else DEFAULT_OUT
    out = Path(str(out).replace("{short}", short))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_doc(turn, system, sys_commit, sys_fallback))
    print(f"turn_id={turn['turn_id']} sys_commit={sys_commit} -> {out}")


if __name__ == "__main__":
    asyncio.run(main())

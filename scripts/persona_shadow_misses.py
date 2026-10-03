#!/usr/bin/env python3
"""Hits semánticos que el match determinista NO recuperó (solo lectura).

Lee los logs de consola de Diana (formato ``ColorExtraFormatter``:
``<fecha> INFO | persona_semantic_shadow turn_id=… top=[…] already_retrieved=[…]``)
y lista, por cada evento ``persona_semantic_shadow``, los elementos del top
semántico cuyo ``already_retrieved`` es ``False``. Al final imprime un resumen
por (canal, sección, id). No toca la base de datos ni la red.

Uso:
    journalctl -u diana --since today | python scripts/persona_shadow_misses.py
    python scripts/persona_shadow_misses.py diana.log --min-score 0.5
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_EVENT_RE = re.compile(r"\|\s*persona_semantic_shadow\s")
_TOP_RE = re.compile(r"\btop=(\[.*?\])(?= already_retrieved=)")
_FLAGS_RE = re.compile(r"\balready_retrieved=(\[[^\]]*\])")
_FIELD_RE = {
    "turn_id": re.compile(r"\bturn_id=(\S+)"),
    "channel_type": re.compile(r"\bchannel_type=(\S+)"),
}


@dataclass(frozen=True)
class ShadowMiss:
    turn_id: str
    channel_type: str
    section: str
    item_id: str
    score: float


def parse_misses(lines: Iterable[str], *, min_score: float = 0.0) -> list[ShadowMiss]:
    """Pure: shadow top entries with ``already_retrieved == False``."""
    out: list[ShadowMiss] = []
    for raw in lines:
        line = _ANSI_RE.sub("", raw)
        if not _EVENT_RE.search(line):
            continue
        top_m, flags_m = _TOP_RE.search(line), _FLAGS_RE.search(line)
        if top_m is None or flags_m is None:
            continue
        try:
            top = ast.literal_eval(top_m.group(1))
            flags = ast.literal_eval(flags_m.group(1))
        except (ValueError, SyntaxError):
            continue
        fields = {k: (m.group(1) if (m := rx.search(line)) else "?") for k, rx in _FIELD_RE.items()}
        for entry, hit in zip(top, flags):
            if hit or not isinstance(entry, dict):
                continue
            score = float(entry.get("score") or 0.0)
            if score < min_score:
                continue
            out.append(ShadowMiss(fields["turn_id"], fields["channel_type"],
                                  str(entry.get("section")), str(entry.get("id")), score))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logfile", nargs="?", help="archivo de log (por defecto stdin)")
    parser.add_argument("--min-score", type=float, default=0.0)
    args = parser.parse_args(argv)
    if args.logfile:
        with open(args.logfile, encoding="utf-8", errors="replace") as fh:
            misses = parse_misses(fh, min_score=args.min_score)
    else:
        misses = parse_misses(sys.stdin, min_score=args.min_score)
    for m in misses:
        print(f"{m.turn_id}\t{m.channel_type}\t{m.section}\t{m.item_id}\t{m.score:.4f}")
    summary = Counter((m.channel_type, m.section, m.item_id) for m in misses)
    print(f"\n# {len(misses)} hits semánticos no recuperados por el match determinista")
    for (channel, section, item_id), n in summary.most_common():
        print(f"# {n}\t{channel}\t{section}\t{item_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Persona semantic shadow (SHADOW — only measures, never changes the prompt).

hardener/persona-reglas ítem 3 (E1), behind ``FEATURE_PERSONA_SEMANTIC_SHADOW``.
After the Director stores ``retrieved``, it hands an immutable snapshot of
strings to :meth:`PersonaSemanticShadow.schedule`, which starts ONE background
task per channel and returns at once (the turn never awaits nor reads it). The
task compares the client message with the channel catalog by embeddings and
logs ids + scores (``persona_semantic_shadow``) — never the client text, never
``nota_privada``, nothing persisted.

Pure-ish cognitive module: stdlib + :mod:`diana.cognitive.tags` only.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol

from diana.cognitive.tags import normalize_tags

logger = logging.getLogger("diana.cognitive.shadow")

SHADOW_TOP_K = 3
_FACTS_CAP = "knowledge.persona_facts"
_POLICY_CAP = "knowledge.policy"
_POLICY_PREFIX = "Trigger: "
_POLICY_SEP = " | Rule:"


class TextEmbedder(Protocol):
    @property
    def is_loaded(self) -> bool: ...

    @property
    def model_name(self) -> str: ...

    async def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class ShadowSnapshot:
    turn_id: str
    channel_type: str
    text: str
    retrieved_fact_hechos: tuple[str, ...]
    retrieved_policy_ids: tuple[str, ...]  # parsed from "Trigger: {pid} | Rule:" lines
    operacion_ids: tuple[str, ...]


def _policy_id_from_line(line: Any) -> str | None:
    if not isinstance(line, str) or not line.startswith(_POLICY_PREFIX):
        return None
    head = line[len(_POLICY_PREFIX):]
    idx = head.find(_POLICY_SEP)
    if idx < 0:
        return None
    return head[:idx].strip() or None


def build_shadow_snapshot(
    turn: Any, retrieved: dict[str, Any], operacion_hits: list[Any] | None
) -> ShadowSnapshot:
    """Pure. Copies str/ids only; never keeps a reference to turn structures."""
    hechos: list[str] = []
    for fact in (retrieved or {}).get(_FACTS_CAP) or []:
        if isinstance(fact, dict) and fact.get("hecho") is not None:
            hechos.append(str(fact["hecho"]))
    policy_ids: list[str] = []
    for line in (retrieved or {}).get(_POLICY_CAP) or []:
        pid = _policy_id_from_line(line)
        if pid is not None:
            policy_ids.append(pid)
    op_ids = [str(getattr(hit, "id", "")) for hit in (operacion_hits or [])]
    return ShadowSnapshot(
        turn_id=str(getattr(turn, "turn_id", "")),
        channel_type=str(getattr(turn, "channel_type", "vip") or "vip"),
        text=str(getattr(turn, "text", "") or ""),
        retrieved_fact_hechos=tuple(hechos),
        retrieved_policy_ids=tuple(policy_ids),
        operacion_ids=tuple(i for i in op_ids if i),
    )


def build_shadow_index_texts(catalog: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """(section, id, text). Allow-list; NEVER nota_privada; voice_patterns not indexed.

    facts: " ".join(temas) + ". " + hecho · policies: temas + ". " + regla ·
    operacion: ", ".join(alias) + ". " + hecho
    """
    if not isinstance(catalog, dict):
        return []
    out: list[tuple[str, str, str]] = []
    for section, body_key in (("persona_facts", "hecho"), ("policies", "regla")):
        items = catalog.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            body = str(item.get(body_key) or "").strip()
            if not body:
                continue
            temas = " ".join(normalize_tags(item.get("tema")))
            out.append((section, str(item["id"]), f"{temas}. {body}" if temas else body))
    items = catalog.get("operacion")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            hecho = str(item.get("hecho") or "").strip()
            alias = [str(a) for a in (item.get("alias") or []) if isinstance(a, str)]
            if not hecho:
                continue
            out.append(("operacion", str(item["id"]), f"{', '.join(alias)}. {hecho}"))
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _top_k_cosine(
    query: list[float],
    keys: list[tuple[str, str]],
    vectors: list[list[float]],
    k: int,
) -> list[dict[str, Any]]:
    scored = [
        (_cosine(query, vec), idx) for idx, vec in enumerate(vectors)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"section": keys[idx][0], "id": keys[idx][1], "score": round(score, 4)}
        for score, idx in scored[: max(0, k)]
    ]


def _already_retrieved(
    top: list[dict[str, Any]], snap: ShadowSnapshot, catalog: dict[str, Any] | None
) -> list[bool]:
    """Per top entry: was it already in the turn's retrieval?

    facts by exact ``hecho`` (retrieved facts carry no id), policies by catalog
    id parsed from the formatted line (DB "Trigger: {description}" lines never
    match a catalog id), operacion by id.
    """
    fact_hecho: dict[str, str] = {}
    if isinstance(catalog, dict):
        for fact in catalog.get("persona_facts") or []:
            if isinstance(fact, dict) and fact.get("id") is not None:
                fact_hecho[str(fact["id"])] = str(fact.get("hecho") or "").strip()
    hechos = set(snap.retrieved_fact_hechos)
    policy_ids = set(snap.retrieved_policy_ids)
    op_ids = set(snap.operacion_ids)
    flags: list[bool] = []
    for entry in top:
        section, item_id = entry.get("section"), str(entry.get("id"))
        if section == "persona_facts":
            flags.append(fact_hecho.get(item_id) in hechos)
        elif section == "policies":
            flags.append(item_id in policy_ids)
        elif section == "operacion":
            flags.append(item_id in op_ids)
        else:
            flags.append(False)
    return flags


class PersonaSemanticShadow:
    """One background measurement per channel at a time; drops when busy."""

    def __init__(self, embedder: TextEmbedder, catalog_provider: Any, *, top_k: int = SHADOW_TOP_K) -> None:
        self._embedder = embedder
        self._provider = catalog_provider
        self._top_k = top_k
        self._tasks: dict[str, asyncio.Task] = {}  # one per channel, strong refs
        # channel → (id(catalog), keys, vectors)
        self._index: dict[str, tuple[int, list[tuple[str, str]], list[list[float]]]] = {}

    def schedule(self, snapshot: ShadowSnapshot) -> bool:
        """O(1), never awaits. False if the channel already has a running task."""
        running = self._tasks.get(snapshot.channel_type)
        if running is not None and not running.done():
            logger.info(
                "persona_semantic_shadow_dropped",
                extra={"turn_id": snapshot.turn_id, "channel_type": snapshot.channel_type},
            )
            return False
        self._tasks[snapshot.channel_type] = asyncio.create_task(self._run(snapshot))
        return True

    async def _ensure_index(
        self, channel_type: str, catalog: dict[str, Any] | None
    ) -> tuple[list[tuple[str, str]], list[list[float]]]:
        """Rebuild the channel index only when the catalog object changes."""
        cached = self._index.get(channel_type)
        if cached is not None and cached[0] == id(catalog):
            return cached[1], cached[2]
        keys: list[tuple[str, str]] = []
        vectors: list[list[float]] = []
        for section, item_id, text in build_shadow_index_texts(catalog):
            vectors.append(list(await self._embedder.embed(text)))
            keys.append((section, item_id))
        self._index[channel_type] = (id(catalog), keys, vectors)
        return keys, vectors

    async def _run(self, snap: ShadowSnapshot) -> None:
        try:
            if not self._embedder.is_loaded:  # never trigger a model load from the shadow
                logger.info(
                    "persona_semantic_shadow_skipped",
                    extra={"turn_id": snap.turn_id, "reason": "model_not_loaded"},
                )
                return
            t0 = time.perf_counter()
            catalog = await self._provider.get_catalog(snap.channel_type)
            keys, vectors = await self._ensure_index(snap.channel_type, catalog)
            e0 = time.perf_counter()
            query = await self._embedder.embed(snap.text)
            embed_ms = (time.perf_counter() - e0) * 1000
            top = _top_k_cosine(list(query), keys, vectors, self._top_k)
            logger.info(
                "persona_semantic_shadow",
                extra={
                    "turn_id": snap.turn_id,
                    "channel_type": snap.channel_type,
                    "model_name": self._embedder.model_name,
                    "top": top,
                    "already_retrieved": _already_retrieved(top, snap, catalog),
                    "index_size": len(keys),
                    "embed_ms": round(embed_ms, 2),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                },
            )
        except Exception:
            logger.exception("persona_semantic_shadow_failed", extra={"turn_id": snap.turn_id})


__all__ = [
    "SHADOW_TOP_K",
    "PersonaSemanticShadow",
    "ShadowSnapshot",
    "TextEmbedder",
    "build_shadow_index_texts",
    "build_shadow_snapshot",
]

"""MemoryBackfillService — VIP profile backfill from message_history (F5-01/F5-08).

Application service (AGENTS.md §2.1: writers live in ``application/``, never
in cognitive/behavior). Turns the full ``message_history`` of a VIP chat into
a sectioned profile written to ``memories`` via ``replace_vip_profile``:

- Flag-gated by ``feature_memory_enabled`` (constructor, pattern
  ``CalibrationService``); no composition wiring in this pool.
- Long histories are paginated in ``window_size`` windows with an
  accumulating prompt so facts are not repeated across windows (F5-08).
- Consolidation is code-side: normalized exact-text dedup across windows;
  semantic dedup 0.85 arrives in Pool 2 (F5-07).
- Sensible facts (section ``sensible`` or ``sensible=True``) are born
  ``pending_owner``; the rest ``auto`` (REQ-MEM-09).
- Idempotent: ``replace_vip_profile`` deletes + reinserts in one transaction,
  so regenerating never duplicates (REQ-MEM-03).
- LLM failure in any window → ``failed`` report with NO partial write (R4).
- Owner gets a best-effort DM summary (pattern ``vip_history_seed``).

Never imports telegram/behavior/infrastructure sessions (purity gates).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from diana.application.ports import MemoryInsert, OwnerNotifierPort

logger = logging.getLogger("diana.application")

__all__ = [
    "BackfillReport",
    "EmbeddingPort",
    "HechoExtracted",
    "HistoryReader",
    "LLMStructuredPort",
    "MemoryBackfillService",
    "MemoryProfileWriter",
    "WindowExtraction",
]

_SECTIONS = ("identidad", "preferencias", "comercial", "limites", "sensible")

_SYSTEM_EXTRACTOR = (
    "Sos un extractor de hechos de perfil de un VIP de un bot de ventas por "
    "Telegram. Leés transcriptos de chats y extraés SOLO hechos que aparezcan "
    "explícitamente en el texto: no inventes, no infieras ni agregues contexto "
    "externo. Respondés en español, con hechos concisos (máximo ~20 palabras "
    "cada uno).\n"
    "Secciones válidas (vocabulario fijo): identidad (datos personales "
    "estables: nombre, ciudad, familia, trabajo, estudios), preferencias "
    "(tono y temas que le funcionan), comercial (historial de compra e "
    "intereses), limites (temas a evitar / límites explícitos del VIP), "
    "sensible (salud, finanzas, ubicación exacta, relaciones).\n"
    "Reglas:\n"
    "- Marcá sensible=true si el hecho toca salud, familia, dinero/pagos, "
    "ubicación exacta o relaciones.\n"
    "- Si una ventana no aporta hechos nuevos, devolvé una lista vacía.\n"
    "- No repitas hechos ya listados como extraídos."
)

_WINDOW_TEMPLATE = (
    "Transcripto del chat (una línea por mensaje):\n{transcript}\n\n"
    "Hechos ya extraídos (NO repetir):\n{already_extracted}\n\n"
    "Extraé los hechos NUEVOS de esta ventana y devolvé el JSON estructurado "
    "con el esquema pedido."
)


class HistoryReader(Protocol):
    """Full chronological history reader (backfill source)."""

    async def list_all(self, chat_id: int, *, page_size: int = 500) -> list[dict]: ...


class LLMStructuredPort(Protocol):
    """Structured generation with the same signature as cognitive LLMProvider."""

    async def generate_structured(
        self, messages: list[dict], schema: type[BaseModel], **kwargs: Any
    ) -> BaseModel: ...


class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class MemoryProfileWriter(Protocol):
    """Idempotent per-VIP profile replacement (application contract)."""

    async def replace_vip_profile(
        self,
        vip_id: UUID,
        *,
        rows: list[MemoryInsert],
        perfil: dict,
        perfil_embedding: list[float],
    ) -> int: ...


class HechoExtracted(BaseModel):
    """One fact extracted by the LLM from a transcript window."""

    seccion: Literal["identidad", "preferencias", "comercial", "limites", "sensible"]
    texto: str
    confianza: float = Field(ge=0.0, le=1.0, default=0.8)
    sensible: bool = False


class WindowExtraction(BaseModel):
    """Structured LLM response for one window."""

    hechos: list[HechoExtracted]


@dataclass(frozen=True)
class BackfillReport:
    """Structured outcome of one ``generate_profile`` run."""

    status: str  # ok | disabled | empty_history | failed
    vip_id: UUID
    sections: int = 0
    facts: int = 0
    pending_owner: int = 0
    windows: int = 0


class MemoryBackfillService:
    """Build/replace a VIP profile from its full message history."""

    def __init__(
        self,
        *,
        feature_memory_enabled: bool,
        history: HistoryReader,
        llm: LLMStructuredPort,
        memories: MemoryProfileWriter,
        embedder: EmbeddingPort,
        notifier: OwnerNotifierPort | None = None,
        window_size: int = 200,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._enabled = feature_memory_enabled
        self._history = history
        self._llm = llm
        self._memories = memories
        self._embedder = embedder
        self._notifier = notifier
        self._window_size = max(1, int(window_size))
        self._clock = clock or (lambda: datetime.now(UTC))

    async def generate_profile(self, vip_id: UUID, chat_id: int) -> BackfillReport:
        """Generate (or regenerate) the VIP profile from history. Idempotent."""
        if not self._enabled:
            logger.info(
                "memory_backfill_disabled",
                extra={"vip_id": str(vip_id), "chat_id": chat_id},
            )
            return BackfillReport(status="disabled", vip_id=vip_id)

        msgs = await self._history.list_all(chat_id, page_size=500)
        if not msgs:
            logger.info(
                "memory_backfill_empty_history",
                extra={"vip_id": str(vip_id), "chat_id": chat_id},
            )
            return BackfillReport(status="empty_history", vip_id=vip_id)

        lines = self._build_transcript(msgs)
        windows = [
            lines[i : i + self._window_size]
            for i in range(0, len(lines), self._window_size)
        ]

        already: list[str] = []
        hechos: list[HechoExtracted] = []
        for idx, window in enumerate(windows, start=1):
            try:
                extracted = await self._extract_window(window, already)
            except Exception:
                logger.exception(
                    "memory_backfill_window_failed",
                    extra={"vip_id": str(vip_id), "chat_id": chat_id, "window": idx},
                )
                # R4: no partial writes — one failed window aborts the run.
                return BackfillReport(status="failed", vip_id=vip_id)
            hechos.extend(extracted)
            already.extend(f"[{h.seccion}] {h.texto}" for h in extracted)

        consolidated = self._consolidate(hechos)
        perfil_json = self._build_perfil(vip_id, consolidated)

        filas: list[MemoryInsert] = []
        pending = 0
        for h in consolidated:
            is_pending = h.seccion == "sensible" or h.sensible
            if is_pending:
                pending += 1
            filas.append(
                MemoryInsert(
                    category=h.seccion,
                    text=h.texto,
                    embedding=await self._embedder.embed(h.texto),
                    confidence=h.confianza,
                    status="pending_owner" if is_pending else "auto",
                    source_turn_id=None,
                    approved_by=None if is_pending else "auto",
                )
            )

        perfil_embedding = await self._embedder.embed(
            json.dumps(perfil_json, ensure_ascii=False, sort_keys=True)
        )
        inserted = await self._memories.replace_vip_profile(
            vip_id, rows=filas, perfil=perfil_json, perfil_embedding=perfil_embedding
        )
        await self._notify_owner(
            vip_id, facts=inserted - 1, pending_owner=pending
        )

        logger.info(
            "memory_backfill_ok",
            extra={
                "vip_id": str(vip_id),
                "chat_id": chat_id,
                "facts": inserted - 1,
                "pending_owner": pending,
                "windows": len(windows),
            },
        )
        return BackfillReport(
            status="ok",
            vip_id=vip_id,
            sections=len(perfil_json["secciones"]),
            facts=inserted - 1,
            pending_owner=pending,
            windows=len(windows),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _extract_window(
        self, lines: list[str], already: list[str]
    ) -> list[HechoExtracted]:
        already_block = "\n".join(f"- {a}" for a in already) if already else "(ninguno)"
        user_content = _WINDOW_TEMPLATE.format(
            transcript="\n".join(lines),
            already_extracted=already_block,
        )
        result = await self._llm.generate_structured(
            [
                {"role": "system", "content": _SYSTEM_EXTRACTOR},
                {"role": "user", "content": user_content},
            ],
            WindowExtraction,
        )
        if not isinstance(result, WindowExtraction):
            raise TypeError(
                f"LLM returned {type(result).__name__}, expected WindowExtraction"
            )
        return list(result.hechos)

    @staticmethod
    def _build_transcript(msgs: list[dict]) -> list[str]:
        """One line per message: ``[YYYY-MM-DD HH:MM] Diana/VIP/? : text``."""
        lines: list[str] = []
        for m in msgs:
            text = (m.get("text") or "").strip()
            if not text:
                continue  # never emit empty lines
            role = m.get("role")
            prefix = "Diana" if role == "owner" else "VIP" if role == "vip" else "?"
            ts = MemoryBackfillService._format_timestamp(m.get("timestamp"))
            if ts:
                lines.append(f"[{ts}] {prefix}: {text}")
            else:
                lines.append(f"{prefix}: {text}")
        return lines

    @staticmethod
    def _format_timestamp(ts: Any) -> str | None:
        """Normalize datetime/ISO-string → ``YYYY-MM-DD HH:MM`` (UTC-naive ok)."""
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts.strftime("%Y-%m-%d %H:%M")
        if isinstance(ts, str) and ts.strip():
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed.strftime("%Y-%m-%d %H:%M")
        return None

    @staticmethod
    def _consolidate(hechos: list[HechoExtracted]) -> list[HechoExtracted]:
        """Code-side consolidation: drop empties + exact-normalized duplicates."""
        seen: set[str] = set()
        out: list[HechoExtracted] = []
        for h in hechos:
            text = (h.texto or "").strip()
            if not text:
                continue
            norm = " ".join(text.casefold().split())
            if norm in seen:
                continue
            seen.add(norm)
            out.append(h)
        return out

    def _build_perfil(
        self, vip_id: UUID, consolidated: list[HechoExtracted]
    ) -> dict:
        now = self._clock()
        now_iso = now.isoformat() if now.tzinfo else now.replace(tzinfo=UTC).isoformat()
        return {
            "vip_id": str(vip_id),
            "secciones": {
                s: [h.texto for h in consolidated if h.seccion == s]
                for s in _SECTIONS
            },
            "generado_el": now_iso,
            "actualizado_el": now_iso,
            "fuente": "backfill",
            "version": 1,
        }

    async def _notify_owner(
        self, vip_id: UUID, *, facts: int, pending_owner: int
    ) -> None:
        """Best-effort owner DM (pattern vip_history_seed._notify_owner)."""
        if self._notifier is None:
            return
        try:
            await self._notifier.notify_info(
                f"Perfil generado para {vip_id} — {facts} hechos, "
                f"{pending_owner} requieren tu aprobación"
            )
        except Exception:
            logger.exception(
                "memory_backfill_notify_failed",
                extra={"vip_id": str(vip_id)},
            )

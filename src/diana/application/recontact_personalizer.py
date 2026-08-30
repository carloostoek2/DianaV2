"""RecontactPersonalizer — reduced-pipeline recontact message (REE-02/COG-15).

The recontact flow never runs the Analyst or the Planner. This component is
the personalization step of the reduced pipeline: it retrieves the VIP's
visible memory, recent profile trend and active policies, then asks the LLM
to rewrite the base recontact template with that context — short, natural,
neutral Mexican Spanish.

Pure fail-soft by contract (AGENTS.md 4.3): any error — retrieval, LLM,
schema — returns the rendered template untouched, so recontact can never
break because of personalization. No Evaluator/Decider here: the decision
(send vs approve) stays in RecontactService/AMS.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger("diana.application")

__all__ = ["RecontactPersonalizer"]

# Facts that must never reach the recontact prompt (sensitive domains).
_EXCLUDED_CATEGORIES = frozenset({"sensible"})
_MAX_FACTS = 12
_MAX_POLICIES = 5
_MAX_CONTEXT_CHARS = 900

_SYSTEM_INSTRUCTION = (
    "Eres Diana, una asistente que retoma contacto con un cliente VIP de forma "
    "cercana y natural. Escribe en español neutro (variante mexicana/neutra): "
    "sin 'vosotros', sin 'apetecer', sin regionalismos. "
    "Reescribe el mensaje de recontacto de la plantilla base personalizándolo "
    "con el contexto del VIP. Reglas: máximo dos frases; no inventes datos; "
    "no menciones información sensible; no prometas regalos, descuentos ni "
    "plazos; mantén el tono y la intención de la plantilla; responde solo con "
    "el mensaje final, sin comillas ni explicaciones."
)


class RecontactPersonalizer:
    """LLM-based template personalization for the recontact reduced pipeline."""

    def __init__(
        self,
        *,
        llm: Any,
        memories: Any,
        policies: Any,
        profiles: Any,
        max_tokens: int = 180,
        max_context_chars: int = _MAX_CONTEXT_CHARS,
    ) -> None:
        self._llm = llm
        self._memories = memories
        self._policies = policies
        self._profiles = profiles
        self._max_tokens = max_tokens
        self._max_context_chars = max_context_chars

    async def personalize(
        self, *, vip_id: UUID, template: str, nombre: str
    ) -> str:
        """Return a personalized recontact message; the template on any failure.

        Fail-soft: retrieval errors, LLM errors and empty output all fall back
        to the rendered template (RecontactService applies placeholders).
        """
        try:
            context = await self._gather_context(vip_id)
        except Exception:
            logger.exception(
                "recontact_personalize_context_failed",
                extra={"vip_id": str(vip_id)},
            )
            return template

        if not context.strip():
            # Nothing to personalize with — the template is the message.
            return template

        messages = [
            {"role": "system", "content": _SYSTEM_INSTRUCTION},
            {
                "role": "user",
                "content": (
                    f"Plantilla base: {template}\n\n"
                    f"Contexto del VIP:\n{context}\n\n"
                    "Escribe el mensaje de recontacto personalizado."
                ),
            },
        ]
        try:
            text = await self._llm.generate(
                messages, temperature=0.8, max_tokens=self._max_tokens
            )
        except Exception:
            logger.exception(
                "recontact_personalize_llm_failed",
                extra={"vip_id": str(vip_id)},
            )
            return template

        cleaned = (text or "").strip().strip('"').strip("“”")
        if not cleaned:
            return template
        logger.info(
            "recontact_personalized",
            extra={"vip_id": str(vip_id), "chars": len(cleaned)},
        )
        return cleaned

    async def _gather_context(self, vip_id: UUID) -> str:
        """Visible VIP context for the prompt (no sensitive facts)."""
        lines: list[str] = []

        facts = await self._memories.list_by_vip(
            vip_id, statuses=("auto", "approved"), limit=_MAX_FACTS
        )
        visible = [
            f
            for f in facts
            if (f.get("category") or "") not in _EXCLUDED_CATEGORIES
        ]
        if visible:
            lines.append("Datos del VIP:")
            for f in visible:
                content = f.get("content") or {}
                texto = str(
                    content.get("texto") or content.get("fact") or ""
                ).strip()
                if texto:
                    lines.append(f"- {texto}")

        try:
            profile = await self._profiles.get_by_vip(vip_id)
        except Exception:
            profile = None
        if profile is not None and getattr(profile, "recent_trend", None):
            trend = profile.recent_trend
            if isinstance(trend, dict) and trend:
                trend_text = "; ".join(
                    f"{k}: {v}" for k, v in list(trend.items())[:4]
                )
                lines.append(f"Tendencia reciente: {trend_text}")
            elif isinstance(trend, str) and trend.strip():
                lines.append(f"Tendencia reciente: {trend.strip()}")

        try:
            policies = await self._policies.list_active_for_vip(
                vip_id, limit=_MAX_POLICIES
            )
        except Exception:
            policies = []
        rules = [
            str(p.get("rule") or "").strip()
            for p in policies
            if str(p.get("rule") or "").strip()
        ]
        if rules:
            lines.append("Reglas de conversación:")
            lines.extend(f"- {r}" for r in rules[:3])

        context = "\n".join(lines)
        if len(context) > self._max_context_chars:
            context = context[: self._max_context_chars - 1] + "…"
        return context

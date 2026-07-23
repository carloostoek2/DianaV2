"""Cognitive-domain exceptions (typed fail reasons for the pipeline)."""

from __future__ import annotations


class AnalystSchemaInvalidError(Exception):
    """Raised when Analyst structured output fails schema after one retry.

    Stable reason string matches contrato_analista.md A.6:
    ``analista_schema_invalido``.
    """

    reason: str = "analista_schema_invalido"

    def __init__(self, reason: str = "analista_schema_invalido") -> None:
        self.reason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason


class EvaluatorSchemaInvalidError(Exception):
    """Raised when Evaluator structured output fails schema after one retry.

    Stable reason string matches contrato_evaluador.md B.6:
    ``evaluador_schema_invalido``.
    """

    reason: str = "evaluador_schema_invalido"

    def __init__(self, reason: str = "evaluador_schema_invalido") -> None:
        self.reason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason


class ContextExceedsLimitError(Exception):
    """Raised when assembled prompt exceeds max_prompt_chars (Anexo D.5/D.6).

    Stable reason: ``contexto_excede_limite``.
    """

    reason: str = "contexto_excede_limite"

    def __init__(self, reason: str = "contexto_excede_limite") -> None:
        self.reason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason


class GeneratorEmptyOutputError(Exception):
    """Raised when Generator returns empty/whitespace after one retry (Anexo E.4).

    Stable reason: ``generador_salida_vacia``.
    """

    reason: str = "generador_salida_vacia"

    def __init__(self, reason: str = "generador_salida_vacia") -> None:
        self.reason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason


__all__ = [
    "AnalystSchemaInvalidError",
    "ContextExceedsLimitError",
    "EvaluatorSchemaInvalidError",
    "GeneratorEmptyOutputError",
]

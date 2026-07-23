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


__all__ = ["AnalystSchemaInvalidError"]

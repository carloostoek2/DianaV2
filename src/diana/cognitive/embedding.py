"""EmbeddingService — lazy-loaded sentence-transformers text vectorization (384 dims).

The model is loaded only on the first call to ``embed()``, never at import time or
constructor time. ``run_in_executor`` avoids blocking the async event loop during
the CPU-bound ``model.encode()`` call.
"""

from __future__ import annotations

import asyncio

__all__ = ["EmbeddingService"]


class EmbeddingService:
    """Lazy-loaded text-to-vector converter using sentence-transformers.

    Singleton-friendly: model is cached after the first ``embed()`` call
    and reused for the lifetime of the process.
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        self._model_name = model_name
        self._model = None  # lazy-loaded on first embed()

    async def embed(self, text: str) -> list[float]:
        """Convert ``text`` to a 384-dimensional embedding vector.

        The underlying sentence-transformers model is loaded on the first call
        and cached for subsequent calls. The encode call runs in a thread pool
        executor to avoid blocking the event loop.
        """
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(self._model_name)
        loop = asyncio.get_running_loop()
        emb = await loop.run_in_executor(None, self._model.encode, text)
        return emb.tolist()

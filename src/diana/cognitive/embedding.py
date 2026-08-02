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

    # Maximum characters of input text fed to the embedding model. Longer text
    # is silently truncated today (preserved behavior for back-compat), but
    # 4.3: we now log a warning when truncation happens so silent data loss is
    # observable. The natural ending of a chat turn is usually where the
    # question lives, so we use the LAST ``max_input_chars`` rather than the
    # first to keep the question in scope for retrieval.
    DEFAULT_MAX_INPUT_CHARS = 2000

    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    ) -> None:
        self._model_name = model_name
        self._max_input_chars = int(max_input_chars)
        self._model = None  # lazy-loaded on first embed()

    async def warmup(self) -> None:
        """Pre-load the model and run one dummy encode.

        Call from boot (main.py) so the first real VIP message after process
        start does not pay the model-load latency. Safe to call multiple
        times; subsequent calls are no-ops once the model is cached.
        """
        if self._model is not None:
            return
        await self.embed("warmup")  # triggers lazy load + caches the model

    async def embed(self, text: str) -> list[float]:
        """Convert ``text`` to a 384-dimensional embedding vector.

        The underlying sentence-transformers model is loaded on the first call
        and cached for subsequent calls. The encode call runs in a thread pool
        executor to avoid blocking the event loop. Inputs longer than
        ``max_input_chars`` are truncated to the trailing window with a
        warning log so silent data loss is observable.
        """
        truncated = False
        original_length = len(text)
        if original_length > self._max_input_chars:
            truncated = True
            text = text[-self._max_input_chars:]
        if truncated:
            import logging

            logging.getLogger(__name__).warning(
                "embedding_text_truncated",
                extra={
                    "max_input_chars": self._max_input_chars,
                    "original_length": original_length,
                },
            )
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(self._model_name)
        loop = asyncio.get_running_loop()
        emb = await loop.run_in_executor(None, self._model.encode, text)
        return emb.tolist()

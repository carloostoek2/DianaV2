"""EmbeddingService — lazy-loaded sentence-transformers text vectorization (384 dims).

The model is loaded only on the first call to ``embed()`` / ``warmup()``, never at
import time or constructor time. The load runs in a worker thread
(``asyncio.to_thread``) behind an ``asyncio.Lock`` with a double check, so it never
blocks the event loop and never happens twice. ``run_in_executor`` avoids blocking
the loop during the CPU-bound ``model.encode()`` call.
"""

from __future__ import annotations

import asyncio
from typing import Any

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
        # Review round 1 (M1): ONE shared load task. Callers await it through
        # asyncio.shield, so cancelling a caller (e.g. a turn timeout) never
        # cancels the load and never starts a second one.
        self._load_task: asyncio.Task[Any] | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load_model(self) -> Any:
        """Blocking model load — always called through ``asyncio.to_thread``."""
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        return SentenceTransformer(self._model_name)

    async def _load_and_cache(self) -> Any:
        model = await asyncio.to_thread(self._load_model)
        self._model = model
        return model

    async def _ensure_model(self) -> Any:
        """Load the model once, off the event loop thread (shared shielded task).

        A failed load is not cached: the next caller starts a new attempt.
        """
        model = self._model
        if model is not None:
            return model
        task = self._load_task
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            task = asyncio.ensure_future(self._load_and_cache())
            # Retrieve the outcome even when every waiter was cancelled
            # (no "Task exception was never retrieved" noise).
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            self._load_task = task
        return await asyncio.shield(task)

    async def warmup(self) -> None:
        """Pre-load the model and run one dummy encode.

        Started from boot (main.py, ``EmbeddingWarmupJob`` in background) so the
        first real VIP message after process start does not pay the model-load
        latency. Safe to call multiple times; subsequent calls are no-ops once
        the model is cached. The load itself runs in a worker thread.
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
        model = await self._ensure_model()
        loop = asyncio.get_running_loop()
        emb = await loop.run_in_executor(None, model.encode, text)
        return emb.tolist()

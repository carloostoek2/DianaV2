"""Unit tests for EmbeddingService — lazy load, 384-dim, thread-pool execution.

The sentence-transformers model is mocked at the library boundary (external dep
that downloads ~80 MB model files). This is PERMITIDO per Mock Audit rules:
the class under test delegates to ``SentenceTransformer.encode()``; mocking
that call lets us verify lazy-load protocol and output shape without a CI model
download.
"""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np

import pytest

from diana.cognitive.embedding import EmbeddingService


def _fake_embedding() -> MagicMock:
    """Return a mock array with .tolist() producing 384 floats."""
    arr = MagicMock()
    arr.tolist.return_value = [0.1] * 384
    return arr


@pytest.mark.asyncio
async def test_embedding_service_model_not_loaded_at_init() -> None:
    """Model is lazy — __init__ must not import sentence_transformers."""
    svc = EmbeddingService()
    assert svc._model is None


@pytest.mark.asyncio
async def test_embedding_service_loads_model_on_first_embed() -> None:
    """First embed() call triggers SentenceTransformer load."""
    fake_result = _fake_embedding()
    fake_model = MagicMock()
    fake_model.encode.return_value = fake_result

    with patch(
        "sentence_transformers.SentenceTransformer",
        return_value=fake_model,
    ) as mock_cls:
        svc = EmbeddingService()
        assert svc._model is None  # not loaded yet

        result = await svc.embed("hola")

        mock_cls.assert_called_once_with("paraphrase-multilingual-MiniLM-L12-v2")
        assert svc._model is not None  # cached after first call
        assert len(result) == 384
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_embedding_service_reuses_cached_model() -> None:
    """Subsequent embed() calls must not re-load the model."""
    fake_result = _fake_embedding()
    fake_model = MagicMock()
    fake_model.encode.return_value = fake_result

    with patch(
        "sentence_transformers.SentenceTransformer",
        return_value=fake_model,
    ) as mock_cls:
        svc = EmbeddingService()

        await svc.embed("first")
        await svc.embed("second")
        await svc.embed("third")

        mock_cls.assert_called_once()  # loaded exactly once
        assert fake_model.encode.call_count == 3


@pytest.mark.asyncio
async def test_embedding_service_returns_list_of_384_floats() -> None:
    """Contract: embed always returns 384-dimensional float list."""
    fake_model = MagicMock()
    fake_model.encode.return_value = _fake_embedding()

    with patch(
        "sentence_transformers.SentenceTransformer",
        return_value=fake_model,
    ):
        svc = EmbeddingService()
        result = await svc.embed("test text")

        assert isinstance(result, list)
        assert len(result) == 384
        for v in result:
            assert isinstance(v, float)


# --- hardener/persona-reglas ítem 3 (D1): una sola carga, en un hilo ---------


@pytest.mark.asyncio
async def test_concurrent_embeds_load_model_once() -> None:
    loads = 0

    class _M:
        def encode(self, text):
            return np.zeros(384)

    def _ctor(name):
        nonlocal loads
        loads += 1
        time.sleep(0.05)
        return _M()

    with patch("sentence_transformers.SentenceTransformer", side_effect=_ctor):
        svc = EmbeddingService()
        await asyncio.gather(*(svc.embed(f"t{i}") for i in range(5)))
    assert loads == 1 and svc.is_loaded


@pytest.mark.asyncio
async def test_model_loads_off_the_event_loop_thread() -> None:
    seen: dict[str, int] = {}

    def _ctor(name):
        seen["thread"] = threading.get_ident()
        return MagicMock(encode=lambda t: np.zeros(384))

    with patch("sentence_transformers.SentenceTransformer", side_effect=_ctor):
        await EmbeddingService().warmup()
    assert seen["thread"] != threading.get_ident()


def test_is_loaded_and_model_name_properties() -> None:
    svc = EmbeddingService(model_name="m")
    assert svc.is_loaded is False and svc.model_name == "m"


@pytest.mark.asyncio
async def test_warmup_twice_loads_once() -> None:
    ctor = MagicMock(return_value=MagicMock(encode=lambda t: np.zeros(384)))
    with patch("sentence_transformers.SentenceTransformer", ctor):
        svc = EmbeddingService()
        await svc.warmup()
        await svc.warmup()
    assert ctor.call_count == 1


@pytest.mark.asyncio
async def test_loop_stays_responsive_during_load() -> None:
    def _ctor(name):
        time.sleep(0.2)
        return MagicMock(encode=lambda t: np.zeros(384))

    order: list[str] = []

    async def _tick():
        await asyncio.sleep(0.01)
        order.append("tick")

    async def _warm(svc):
        await svc.warmup()
        order.append("warm")

    with patch("sentence_transformers.SentenceTransformer", side_effect=_ctor):
        svc = EmbeddingService()
        await asyncio.gather(_warm(svc), _tick())
    assert order == ["tick", "warm"]



# --- Review round 1 (M1): cancelling a caller never loads the model twice ----


@pytest.mark.asyncio
async def test_cancelled_first_caller_does_not_cause_a_second_load() -> None:
    loads = 0
    started = threading.Event()

    def _ctor(name):
        nonlocal loads
        loads += 1
        started.set()
        time.sleep(0.1)
        return MagicMock(encode=lambda t: np.zeros(384))

    with patch("sentence_transformers.SentenceTransformer", side_effect=_ctor):
        svc = EmbeddingService()
        first = asyncio.create_task(svc.embed("a"))
        while not started.is_set():
            await asyncio.sleep(0.005)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = await svc.embed("b")
    assert loads == 1 and svc.is_loaded and len(second) == 384


@pytest.mark.asyncio
async def test_failed_load_is_retried_by_the_next_caller() -> None:
    calls = 0

    def _ctor(name):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("model files missing")
        return MagicMock(encode=lambda t: np.zeros(384))

    with patch("sentence_transformers.SentenceTransformer", side_effect=_ctor):
        svc = EmbeddingService()
        with pytest.raises(OSError):
            await svc.embed("a")
        assert not svc.is_loaded
        await svc.embed("b")
    assert calls == 2 and svc.is_loaded

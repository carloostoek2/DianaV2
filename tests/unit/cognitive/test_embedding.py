"""Unit tests for EmbeddingService — lazy load, 384-dim, thread-pool execution.

The sentence-transformers model is mocked at the library boundary (external dep
that downloads ~80 MB model files). This is PERMITIDO per Mock Audit rules:
the class under test delegates to ``SentenceTransformer.encode()``; mocking
that call lets us verify lazy-load protocol and output shape without a CI model
download.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

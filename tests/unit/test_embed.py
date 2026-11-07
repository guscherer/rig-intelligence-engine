"""Testes unitários do backfill de embeddings (sem rede/modelo)."""

from __future__ import annotations

import importlib

import pytest

from rig.retrieval.embed import (
    BackfillStats,
    backfill_embeddings,
    embedding_dim,
    encode_texts,
    load_encoder,
    model_name,
    validate_dimension,
)


class _FakeEncoder:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def encode(self, texts, batch_size=None):
        return [[0.25] * self.dim for _ in texts]


def test_embedding_dim_default_and_env(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DIM", raising=False)
    assert embedding_dim() == 1024
    monkeypatch.setenv("EMBEDDING_DIM", "8")
    assert embedding_dim() == 8


def test_model_name_env(monkeypatch):
    monkeypatch.setenv("MODEL_EMBEDDING", "foo/bar")
    assert model_name() == "foo/bar"


def test_validate_dimension_ok_and_fail():
    validate_dimension([0.0] * 4, 4)
    with pytest.raises(ValueError):
        validate_dimension([0.0] * 3, 4)


def test_encode_texts_validates_dim(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "4")
    enc = _FakeEncoder(dim=4)
    out = encode_texts(enc, ["a", "b"], batch_size=2)
    assert len(out) == 2
    assert len(out[0]) == 4
    with pytest.raises(ValueError):
        encode_texts(_FakeEncoder(dim=3), ["a"], batch_size=1)


async def test_backfill_with_fake_encoder_no_db():
    enc = _FakeEncoder(dim=1024)
    rows = [("c1", "texto um"), ("c2", "texto dois")]
    stats = await backfill_embeddings(rows=rows, encoder=enc, batch_size=2)
    assert isinstance(stats, BackfillStats)
    assert stats.total == 2
    assert stats.embedded == 2
    assert stats.failed == 0
    assert stats.throughput >= 0


async def test_backfill_idempotent_second_run_empty():
    enc = _FakeEncoder(dim=1024)
    stats = await backfill_embeddings(rows=[], encoder=enc)
    assert stats.total == 0
    assert stats.embedded == 0


def test_load_encoder_missing_raises(monkeypatch):
    real_import = importlib.import_module

    def fake_import(name, *a, **k):
        if name == "sentence_transformers":
            raise ImportError("missing")
        return real_import(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(RuntimeError):
        load_encoder()


async def test_backfill_dim_override(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "4")
    enc = _FakeEncoder(dim=4)
    stats = await backfill_embeddings(rows=[("c", "t")], encoder=enc, dim=4)
    assert stats.dim == 4
    assert stats.embedded == 1


class _FailingEncoder:
    def __init__(self, dim: int = 4, fail_on: set[str] | None = None) -> None:
        self.dim = dim
        self.fail_on = fail_on or set()

    def encode(self, texts, batch_size=None):
        for text in texts:
            if text in self.fail_on:
                raise ValueError(f"bad text: {text}")
        return [[0.25] * self.dim for _ in texts]


async def test_backfill_isolates_bad_chunk():
    enc = _FailingEncoder(dim=4, fail_on={"ruim"})
    rows = [("c1", "ok"), ("c2", "ruim"), ("c3", "ok2")]
    stats = await backfill_embeddings(rows=rows, encoder=enc, batch_size=2, dim=4)
    assert stats.total == 3
    assert stats.embedded == 2
    assert stats.failed == 1
    assert any("chunk_id=c2" in err for err in stats.errors)

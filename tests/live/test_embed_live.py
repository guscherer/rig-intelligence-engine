"""Testes live do modelo real (fora do gate padrão)."""

from __future__ import annotations

import pytest

from rig.retrieval.embed import embedding_dim, load_encoder


@pytest.mark.live
@pytest.mark.slow
def test_real_model_dim():
    enc = load_encoder()
    vec = enc.encode(["teste de embedding jurídico"], batch_size=1)
    v = vec[0].tolist() if hasattr(vec[0], "tolist") else list(vec[0])
    assert len(v) == embedding_dim() == 1024

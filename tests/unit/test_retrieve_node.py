from __future__ import annotations

import pytest

from rig.agents.retrieve import retrieve


@pytest.mark.asyncio
async def test_retrieve_applies_filters_and_propagates_error() -> None:
    class FakeStore:
        async def search(self, query, *, filters=None):
            return [{"chunk_id": "c1", "doc_id": "d1", "score": 0.9, "breadcrumb": "Art. 1"}]

    res = await retrieve("q", store=FakeStore(), kind="dispositivo", ano=2024, tema="t")
    assert len(res) == 1
    assert res[0].chunk_id == "c1"
    assert res.filters_used == ["kind", "ano", "tema"]

    class BadStore:
        async def search(self, query, *, filters=None):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await retrieve("q", store=BadStore())

    class EmptyStore:
        async def search(self, query, *, filters=None):
            return []

    empty = await retrieve("q", store=EmptyStore())
    assert empty == []

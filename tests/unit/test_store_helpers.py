from __future__ import annotations

from rig.ingestion.store import (
    _as_dict,
    _chunk_field,
    _chunk_hash,
    _chunk_id,
    _chunk_text,
    _doc_content_hash,
)


def test_as_dict_none():
    assert _as_dict(None) == {}


def test_as_dict_dict():
    assert _as_dict({"a": 1}) == {"a": 1}


def test_as_dict_iterable():
    assert _as_dict([("a", 1)]) == {"a": 1}


def test_as_dict_unconvertible():
    assert _as_dict(42) == {}


class Obj:
    def __init__(self):
        self.text = "t"
        self.chunk_id = "c"
        self.content_hash = "h"


def test_chunk_text_object():
    assert _chunk_text(Obj()) == "t"


def test_chunk_text_dict():
    assert _chunk_text({"text": "x", "chunk_text": "y"}) == "x"
    assert _chunk_text({"chunk_text": "y"}) == "y"


def test_chunk_text_str():
    assert _chunk_text("raw") == "raw"


def test_chunk_id_object():
    assert _chunk_id(Obj()) == "c"


def test_chunk_id_dict():
    assert _chunk_id({"chunk_id": "d"}) == "d"


def test_chunk_id_fallback():
    assert _chunk_id("x") == ""


def test_chunk_hash_object():
    assert _chunk_hash(Obj()) == "h"


def test_chunk_hash_dict():
    assert _chunk_hash({"content_hash": "hh"}) == "hh"


def test_chunk_hash_fallback():
    assert _chunk_hash("abc") == "sha256:" + __import__("hashlib").sha256(b"abc").hexdigest()


def test_chunk_field():
    o = Obj()
    assert _chunk_field(o, "text") == "t"
    assert _chunk_field({"text": "d"}, "text") == "d"
    assert _chunk_field("x", "text", "default") == "default"


def test_doc_content_hash_explicit():
    assert _doc_content_hash([], "explicit") == "explicit"


def test_doc_content_hash_from_chunks():
    result = _doc_content_hash([Obj()], None)
    assert result.startswith("sha256:")

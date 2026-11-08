"""Testes do CLI de busca (scripts/search.py) — sem rede/modelo/banco."""

from __future__ import annotations

from scripts.search import _build_parser


def test_search_cli_default_mode_is_dense() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.mode == "dense"


def test_search_cli_mode_choices_include_all_three() -> None:
    parser = _build_parser()
    for mode in ("dense", "rrf", "rrf+rerank"):
        args = parser.parse_args(["--mode", mode, "consulta"])
        assert args.mode == mode

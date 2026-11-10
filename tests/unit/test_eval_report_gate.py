"""Testes do gate em scripts/eval_report.py (F0.7).

Sem Postgres, rede ou embeddings: monkeypatch de `_run_cmd`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
MODULE_PATH = ROOT / "scripts" / "eval_report.py"

spec = importlib.util.spec_from_file_location("eval_report_gate", MODULE_PATH)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _fake_run_factory(*, pytest_out: str = "131 passed", ruff_code: int = 0):
    def fake(cmd):
        joined = " ".join(cmd)
        if "pytest" in joined:
            return 0, pytest_out
        if "ruff" in joined and "check" in joined:
            return ruff_code, "" if ruff_code == 0 else "ruff failed"
        if "ruff" in joined and "format" in joined:
            return 0, ""
        if "mypy" in joined:
            return 0, ""
        if "lint-imports" in joined:
            return 0, ""
        return 0, ""

    return fake


def _patch_common(monkeypatch, tmp_path, fake_run):
    monkeypatch.setattr(mod, "_run_cmd", fake_run)
    monkeypatch.setattr(mod, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(mod, "gather_commit", lambda: "abc123 2026-01-01 main")
    monkeypatch.setattr(mod, "gather_corpus", lambda: "documents=1 chunks=2")
    monkeypatch.setattr(mod, "gather_retrieval", lambda: "recall@8 (dense)=0.950")


def test_gate_green(monkeypatch, tmp_path, capsys):
    fake = _fake_run_factory(pytest_out="131 passed")
    _patch_common(monkeypatch, tmp_path, fake)
    rc = mod.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "131 passed" in captured.out
    assert "FAILED" not in captured.out
    report_files = list((tmp_path / "reports").glob("eval-*.md"))
    assert report_files
    text = report_files[0].read_text(encoding="utf-8")
    assert "131 passed" in text
    assert "FAILED" not in text


def test_gate_degraded(monkeypatch, tmp_path, capsys):
    fake = _fake_run_factory(pytest_out="115 passed, 16 skipped")
    _patch_common(monkeypatch, tmp_path, fake)
    rc = mod.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "skipped" in captured.out
    assert "16" in captured.out
    report_files = list((tmp_path / "reports").glob("eval-*.md"))
    assert report_files
    text = report_files[0].read_text(encoding="utf-8")
    assert "skipped" in text
    assert "16" in text


def test_gate_failed_step(monkeypatch, tmp_path, capsys):
    fake = _fake_run_factory(pytest_out="131 passed", ruff_code=1)
    _patch_common(monkeypatch, tmp_path, fake)
    rc = mod.main()
    captured = capsys.readouterr()
    assert rc != 0
    assert "FAILED" in captured.out
    report_files = list((tmp_path / "reports").glob("eval-*.md"))
    assert report_files, "arquivo deve ser escrito mesmo com gate falhando"
    text = report_files[0].read_text(encoding="utf-8")
    assert "FAILED" in text


def test_gather_gate_skipped(monkeypatch):
    fake = _fake_run_factory(pytest_out="115 passed, 16 skipped")
    monkeypatch.setattr(mod, "_run_cmd", fake)
    gate = mod.gather_gate()
    assert "skipped" in gate
    assert "16" in gate
    assert "FAILED" not in gate

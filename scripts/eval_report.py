"""Gera reports/eval-<data>.md com proveniencia (commit, corpus, gate, retrieval).

Uso: `make eval` (ou `uv run python scripts/eval_report.py`).

Reusa (nao reimplementa):
- scripts/eval_retrieval.py / eval/results/recall_v1.json (retrieval)
- Postgres rig-db (corpus: documents/chunks)
- gate real (ruff, format, mypy, lint-imports, pytest)

Exit 0 quando o arquivo foi escrito e o gate (ruff, format, mypy, arch, pytest)
estiver verde. Exit != 0 se o arquivo nao pode ser escrito OU se qualquer passo
do gate retornar codigo != 0 (relatorio ainda e escrito nesse caso).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
JSON_PATH = ROOT / "eval" / "results" / "recall_v1.json"
COMMAND = "uv run python scripts/eval_report.py"


def _git(args: list[str]) -> str:
    try:
        out = subprocess.check_output(  # noqa: S603 - git do PATH, args fixos do script
            ["git", *args],  # noqa: S607
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"
    return out.strip()


def gather_commit() -> str:
    sha = _git(["rev-parse", "--short", "HEAD"])
    branch = _git(["branch", "--show-current"])
    utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{sha} {utc} {branch}"


def _normalize_db_url(url: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.split("+")[0] + "://", 1)
    return url


async def _corpus_direct() -> tuple[int, int] | None:
    url = _normalize_db_url(
        os.environ.get("DATABASE_URL", "postgresql://rig:***@localhost:5432/rig")
    )
    try:
        import asyncpg  # noqa: PLC0415 - dep opcional em runtime
    except ImportError:
        return None
    pool = None
    try:
        pool = await asyncpg.create_pool(url, min_size=1, max_size=1, timeout=5)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "select (select count(*) from documents) as docs, "
                "(select count(*) from chunks) as chunks"
            )
        return int(row["docs"]), int(row["chunks"])
    except Exception:
        return None
    finally:
        if pool is not None:
            with contextlib.suppress(Exception):
                await pool.close()


def _parse_psql_output(text: str) -> tuple[int, int] | None:
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
    # fallback: primeiros dois inteiros da saida
    nums = re.findall(r"\d+", text)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    return None


def _corpus_via_docker() -> tuple[int, int] | None:
    psql_args = [
        "psql",
        "-U",
        "rig",
        "-d",
        "rig",
        "-t",
        "-A",
        "-c",
        "select (select count(*) from documents) as docs, (select count(*) from chunks) as chunks;",
    ]
    candidates = [
        ["docker", "exec", "rig-db", *psql_args],
        ["wsl.exe", "-d", "Ubuntu", "--", "docker", "exec", "rig-db", *psql_args],
    ]
    for cmd in candidates:
        try:
            res = subprocess.run(  # noqa: S603 - docker do PATH, comando fixo
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if res.returncode != 0:
            continue
        parsed = _parse_psql_output(res.stdout)
        if parsed is not None:
            return parsed
    return None


def gather_corpus() -> str:
    direct = asyncio.run(_corpus_direct())
    if direct is not None:
        docs, chunks = direct
        return f"documents={docs} chunks={chunks}"
    docker = _corpus_via_docker()
    if docker is not None:
        docs, chunks = docker
        return f"documents={docs} chunks={chunks}"
    return "not_measured: Postgres (rig-db) inacessivel neste host"


def _run_cmd(cmd: list[str]) -> tuple[int, str]:
    try:
        res = subprocess.run(  # noqa: S603 - uv do PATH, comando fixo
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    out = (res.stdout + "\n" + res.stderr).strip()
    return res.returncode, out


def gather_gate() -> str:
    steps = [
        ("ruff", ["uv", "run", "ruff", "check", "."]),
        ("format", ["uv", "run", "ruff", "format", "--check", "."]),
        ("mypy", ["uv", "run", "mypy"]),
        ("arch", ["uv", "run", "lint-imports", "--no-logo"]),
        ("pytest", ["uv", "run", "pytest", "-m", "not live"]),
    ]
    results: list[tuple[str, int, str]] = []
    for name, cmd in steps:
        code, out = _run_cmd(cmd)
        results.append((name, code, out))

    pytest_passed = 0
    pytest_failed = 0
    pytest_skipped = 0
    pytest_out = next((o for n, _, o in results if n == "pytest"), "")
    m_passed = re.search(r"(\d+)\s+passed", pytest_out)
    m_failed = re.search(r"(\d+)\s+failed", pytest_out)
    m_skipped = re.search(r"(\d+)\s+skipped", pytest_out)
    if m_passed:
        pytest_passed = int(m_passed.group(1))
    if m_failed:
        pytest_failed = int(m_failed.group(1))
    if m_skipped:
        pytest_skipped = int(m_skipped.group(1))

    failed_steps = [name for name, code, _ in results if code != 0]
    status_bits = ", ".join(f"{name}={'OK' if code == 0 else 'FAIL'}" for name, code, _ in results)
    if failed_steps:
        return f"FAILED — {', '.join(failed_steps)} ({status_bits})"
    return (
        f"{pytest_passed} passed, {pytest_failed} failed, {pytest_skipped} skipped ({status_bits})"
    )


def gather_retrieval() -> str:
    if not JSON_PATH.is_file():
        return "not_measured: eval/results/recall_v1.json ausente"
    try:
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"not_measured: falha ao ler eval/results/recall_v1.json ({exc})"
    variants = data.get("variants") or []
    dense = next((v for v in variants if v.get("variant") == "dense"), None)
    if dense is None and variants:
        dense = variants[0]
    if dense is None:
        return "not_measured: recall@8 ausente em eval/results/recall_v1.json"
    val = dense.get("recall_at_8")
    if val is None:
        return "not_measured: recall@8 (dense) ausente em eval/results/recall_v1.json"
    return f"recall@8 (dense)={val:.3f} — eval/results/recall_v1.json"


def render_report(
    *,
    commit: str,
    corpus: str,
    gate: str,
    retrieval: str,
    command: str = COMMAND,
    generated_at: str | None = None,
) -> str:
    if generated_at is None:
        generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Eval report",
        "",
        f"generated_at: {generated_at}",
        f"commit: {commit}",
        f"corpus: {corpus}",
        f"gate: {gate}",
        f"retrieval: {retrieval}",
        f"command: {command}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    commit = gather_commit()
    corpus = gather_corpus()
    gate = gather_gate()
    retrieval = gather_retrieval()
    gate_failed = gate.startswith("FAILED")
    report = render_report(
        commit=commit,
        corpus=corpus,
        gate=gate,
        retrieval=retrieval,
        command=COMMAND,
    )
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        date = datetime.now(UTC).date().isoformat()
        out_path = REPORTS_DIR / f"eval-{date}.md"
        out_path.write_text(report, encoding="utf-8")
    except OSError as exc:
        print(f"erro ao escrever relatorio: {exc}", file=sys.stderr)
        return 1
    print(f"Relatório: {out_path}")
    print(f"commit: {commit}")
    print(f"corpus: {corpus}")
    print(f"gate: {gate}")
    print(f"retrieval: {retrieval}")
    return 1 if gate_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Testes de arquitetura: as fronteiras de docs/10 §1, executáveis.

`make arch` roda o import-linter (contratos de camada). Estes testes cobrem o
que o import-linter não vê: SDK de fornecedor importado fora de adapters/ e
módulo de produção alcançando o harness de avaliação por caminho indireto.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "rig"

PROVIDER_SDKS = {"google", "openai", "anthropic", "cohere", "mistralai"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_modules(path: Path) -> set[str]:
    """Caminhos de módulo completos importados (``import x.y`` e ``from x.y import ...``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _py_files(*excluded: str) -> list[Path]:
    return [
        p
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts and not any(part in excluded for part in p.parts)
    ]


def test_provider_sdk_only_inside_adapters() -> None:
    offenders = [
        str(p.relative_to(SRC)) for p in _py_files("adapters") if _imported_roots(p) & PROVIDER_SDKS
    ]
    assert not offenders, (
        "SDK de provedor importado fora de adapters/ (DIP, docs/10 §4): "
        f"{offenders}. Use o protocolo StructuredGenerator."
    )


def test_production_never_imports_eval() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in _py_files("eval", "api")
        if "rig.eval" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"producao importa rig.eval: {offenders}"


def test_core_has_no_internal_dependencies() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in (SRC / "core").rglob("*.py")
        if any(
            m in p.read_text(encoding="utf-8") for m in ("rig.agents", "rig.api", "rig.ingestion")
        )
    ]
    assert not offenders, f"rig.core depende de camada superior: {offenders}"


def test_state_does_not_import_graph_nodes() -> None:
    """``rig.graph.state`` é a raiz do grafo: não pode importar ``rig.graph.nodes``.

    Se importar, fecha o ciclo ``state -> nodes/__init__ -> nodes.audit -> state``
    (F2.11): ``PositioningBrief`` mora em ``rig.core.types`` justamente para o
    ``RIGState.position`` tipar sem depender dos nós.
    """
    state = SRC / "graph" / "state.py"
    offenders = sorted(m for m in _imported_modules(state) if m.startswith("rig.graph.nodes"))
    assert not offenders, (
        "rig.graph.state importa rig.graph.nodes (ciclo F2.11): "
        f"{offenders}. Tipos devem vir de rig.core.types."
    )


def test_graph_importing_api_fails_importlinter(tmp_path: Path) -> None:
    """Prova negativa: um import ``rig.graph -> rig.api`` reprovaria o gate.

    Usa uma cópia descartável em ``tmp_path`` (com ``PYTHONPATH`` apontando
    para a cópia) em vez de escrever dentro de ``src/``, evitando colisão em
    execução paralela e sujeira na árvore se o processo morrer.
    """
    project_root = Path(__file__).resolve().parents[2]
    src_copy = tmp_path / "src"
    shutil.copytree(project_root / "src", src_copy)
    shutil.copy2(project_root / ".importlinter", tmp_path / ".importlinter")

    offender = src_copy / "rig" / "graph" / "_negtest_offender.py"
    offender.write_text("from rig.api import routers  # noqa: F401\n", encoding="utf-8")

    cache_dir = tmp_path / "cache"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src_copy) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    config_path = tmp_path / ".importlinter"
    code = (
        "import importlinter.configuration; importlinter.configuration.configure(); "
        "from importlinter.application.use_cases import lint_imports; "
        "import sys; "
        f"ok = lint_imports(config_filename={str(config_path)!r}, no_logo=True, "
        f"cache_dir={str(cache_dir)!r}); "
        "sys.exit(0 if ok else 1)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "broken" in combined.lower(), combined

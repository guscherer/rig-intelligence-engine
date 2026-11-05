"""Relatório de tamanho: warning, não gate (docs/10 §2).

LOC por arquivo é sinal, não objetivo. O que este script sinaliza é o que a
revisão humana deve olhar: módulo acima do limite duro sem justificativa
declarada no docstring, classe gigante e função longa que escapou do ruff
(desativado só por `# noqa`, que aqui aparece no relatório).
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

SRC = Path("src/rig")
MODULE_SOFT, MODULE_HARD = 400, 600
CLASS_SOFT, CLASS_HARD = 200, 300
FUNC_SOFT, FUNC_HARD = 40, 60

# Exceções legítimas declaradas na spec: são dados, não lógica.
ALLOWED_LARGE = {
    "src/rig/core/models.py",
    "src/rig/audit/hard_rules.py",
}


@dataclass(frozen=True)
class Finding:
    path: str
    kind: str
    name: str
    size: int
    limit: int

    @property
    def hard(self) -> bool:
        return self.size > self.limit


def _span(node: ast.AST) -> int:
    return (getattr(node, "end_lineno", 0) or 0) - (getattr(node, "lineno", 0) or 0) + 1


def _has_justification(tree: ast.Module) -> bool:
    doc = ast.get_docstring(tree) or ""
    return "justificativa" in doc.lower() or "tabela de" in doc.lower()


def scan(path: Path) -> list[Finding]:
    rel = str(path).replace("\\", "/")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    findings: list[Finding] = []

    module_loc = len(source.splitlines())
    if module_loc > MODULE_SOFT and str(path) not in ALLOWED_LARGE and not _has_justification(tree):
        findings.append(Finding(rel, "module", path.name, module_loc, MODULE_HARD))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            loc = _span(node)
            if loc > CLASS_SOFT:
                findings.append(Finding(rel, "class", node.name, loc, CLASS_HARD))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            loc = _span(node)
            if loc > FUNC_SOFT:
                findings.append(Finding(rel, "function", node.name, loc, FUNC_HARD))

    return findings


def main() -> int:
    findings = [
        f
        for path in sorted(SRC.rglob("*.py"))
        if "__pycache__" not in path.parts
        for f in scan(path)
    ]

    if not findings:
        print(f"size: nenhum alvo acima do limite brando ({len(list(SRC.rglob('*.py')))} arquivos)")
        return 0

    hard_failures = 0
    for f in sorted(findings, key=lambda f: -f.size):
        flag = "FALHA" if f.hard and f.path not in ALLOWED_LARGE else "aviso"
        hard_failures += int(flag == "FALHA")
        print(f"{flag:6} {f.kind:8} {f.size:>4} linhas  (limite {f.limit})  {f.path}::{f.name}")

    print(f"\n{len(findings)} alvos, {hard_failures} acima do limite duro sem justificativa")
    return 0  # warning por contrato: não quebra o build (docs/10 §6)


if __name__ == "__main__":
    sys.exit(main())

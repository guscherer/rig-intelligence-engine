"""Pacote adapters do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1). Aqui vive o SDK/transporte do
provedor de geracao (ADR-012); nada fora de ``rig/adapters/`` fala HTTP com o
provedor.
"""

from rig.adapters.deepseek import (
    DeepSeekGenerator,
    Generation,
    GenerationError,
    StructuredGenerator,
    Usage,
)

__all__ = [
    "DeepSeekGenerator",
    "Generation",
    "GenerationError",
    "StructuredGenerator",
    "Usage",
]

"""Tipos de domínio puros do núcleo RIG.

Aqui moram os tipos (Pydantic) que não dependem de nenhum nó do grafo.
``PositioningBrief`` vive em ``rig.core`` — não em ``rig.graph.nodes`` — porque
``rig.graph.state`` precisa tipar ``RIGState.position`` sem fechar o ciclo
``state -> nodes/__init__ -> nodes.audit -> state`` (F2.11).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PositioningBrief(BaseModel):
    """Restrições institucionais do posicionamento (docs/03 §4).

    Define o que a minuta **não** pode dizer: limites da casa e escopo
    institucional. Produzido pelo nó ``positioning``; consumido pelo ``draft``
    como restrição, não como texto recuperado.
    """

    model_config = ConfigDict(extra="forbid")

    restricoes: list[str] = Field(default_factory=list)
    escopo: str = ""
    fonte_restricoes: list[str] = Field(default_factory=list)
    insuficiente: bool = False


__all__ = ["PositioningBrief"]

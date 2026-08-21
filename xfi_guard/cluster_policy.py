"""Conservative policy for deciding when a threat is safe to share globally."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusterDecision:
    allowed: bool
    reason: str


def evaluate(score: int, risk: str, nodes: int, *, require_two_nodes: bool = False) -> ClusterDecision:
    score = max(0, min(100, int(score)))
    risk = str(risk).lower()
    if score < 90 or risk not in {"critical", "high"}:
        return ClusterDecision(False, "threat does not meet global threshold")
    if require_two_nodes and nodes < 2:
        return ClusterDecision(False, "requires confirmation from at least two VPS nodes")
    return ClusterDecision(True, "global threat threshold satisfied")

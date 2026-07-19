from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal


Direction = Literal["bullish", "bearish", "neutral", "unknown"]
EvidenceRole = Literal[
    "supporting",
    "contradictory",
    "decisive",
    "context",
    "risk",
    "invalidator",
]


@dataclass
class Witness:
    engine: str
    claim: str
    direction: Direction
    score: float
    confidence: float
    importance: float
    role: EvidenceRole
    evidence: List[str] = field(default_factory=list)
    invalidators: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def strength(self) -> float:
        directional_distance = abs(self.score - 50.0) / 50.0
        return round(directional_distance * self.confidence * self.importance, 6)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["strength"] = self.strength
        return payload

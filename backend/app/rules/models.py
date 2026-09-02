from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Mapping

Choice = Literal["A", "B"]


@dataclass(frozen=True)
class RuleSpec:
    initial_score: int = 1
    majority_reward: int = 1
    minority_penalty: int = 1
    score_floor: int = 0
    tie_breaker: str = "parent_choice"
    parent_collects_from_minority: bool = True
    parent_collects_when_minority_has_zero: bool = True
    minority_parent_pays_to_table: bool = True

    def as_dict(self) -> dict[str, int | str | bool]:
        return asdict(self)


@dataclass(frozen=True)
class RoundInput:
    player_ids: tuple[str, ...]
    parent_id: str
    choices: Mapping[str, Choice]
    scores: Mapping[str, int]


@dataclass(frozen=True)
class RoundResolution:
    counts: dict[Choice, int]
    majority_choice: Choice
    score_changes: dict[str, int]
    scores_after: dict[str, int]

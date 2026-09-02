from __future__ import annotations

from .models import Choice, RoundInput, RoundResolution, RuleSpec


class MajorityPartyRules:
    """Pure, deterministic rules for one Majority Party game."""

    def __init__(self, spec: RuleSpec | None = None) -> None:
        self.spec = spec or RuleSpec()

    def starting_scores(self, player_ids: tuple[str, ...] | list[str]) -> dict[str, int]:
        return {player_id: self.spec.initial_score for player_id in player_ids}

    def settle_round(self, value: RoundInput) -> RoundResolution:
        player_ids = set(value.player_ids)
        if len(player_ids) != len(value.player_ids):
            raise ValueError("Player IDs must be unique")
        if value.parent_id not in player_ids:
            raise ValueError("Parent must be an active player")
        if value.parent_id not in value.choices:
            raise ValueError("Parent must answer before scoring")
        if unknown_players := set(value.choices) - player_ids:
            raise ValueError(f"Answers contain unknown players: {sorted(unknown_players)}")

        counts: dict[Choice, int] = {
            "A": sum(choice == "A" for choice in value.choices.values()),
            "B": sum(choice == "B" for choice in value.choices.values()),
        }
        parent_choice = value.choices[value.parent_id]
        if counts["A"] == counts["B"]:
            if self.spec.tie_breaker != "parent_choice":
                raise ValueError(f"Unsupported tie breaker: {self.spec.tie_breaker}")
            majority_choice: Choice = parent_choice
        else:
            majority_choice = "A" if counts["A"] > counts["B"] else "B"
        changes = {player_id: 0 for player_id in value.player_ids}

        for player_id, choice in value.choices.items():
            if choice == majority_choice:
                changes[player_id] += self.spec.majority_reward
                continue

            current_score = max(self.spec.score_floor, value.scores.get(player_id, self.spec.score_floor))
            pays_penalty = player_id != value.parent_id or self.spec.minority_parent_pays_to_table
            paid = min(self.spec.minority_penalty, current_score - self.spec.score_floor) if pays_penalty else 0
            changes[player_id] -= paid

            if player_id != value.parent_id and self.spec.parent_collects_from_minority:
                parent_gain = self.spec.minority_penalty if self.spec.parent_collects_when_minority_has_zero else paid
                changes[value.parent_id] += parent_gain

        scores_after = {
            player_id: max(
                self.spec.score_floor,
                value.scores.get(player_id, self.spec.score_floor) + changes[player_id],
            )
            for player_id in value.player_ids
        }
        return RoundResolution(
            counts=counts,
            majority_choice=majority_choice,
            score_changes=changes,
            scores_after=scores_after,
        )


MAJORITY_PARTY_RULES = MajorityPartyRules()

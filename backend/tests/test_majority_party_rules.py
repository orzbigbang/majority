import pytest

from app.rules import MajorityPartyRules, RoundInput, RuleSpec


def settle(
    choices: dict[str, str],
    scores: dict[str, int] | None = None,
    *,
    parent_id: str = "parent",
):
    players = tuple(scores or choices)
    return MajorityPartyRules().settle_round(
        RoundInput(
            player_ids=players,
            parent_id=parent_id,
            choices=choices,  # type: ignore[arg-type]
            scores=scores or {player_id: 1 for player_id in players},
        )
    )


def test_every_player_starts_with_one_point():
    assert MajorityPartyRules().starting_scores(["parent", "guest"]) == {
        "parent": 1,
        "guest": 1,
    }


def test_majority_scores_and_parent_collects_from_minority():
    result = settle({"parent": "A", "ally": "A", "minority": "B"})

    assert result.counts == {"A": 2, "B": 1}
    assert result.majority_choice == "A"
    assert result.score_changes == {"parent": 2, "ally": 1, "minority": -1}
    assert result.scores_after == {"parent": 3, "ally": 2, "minority": 0}


def test_tie_is_won_by_the_parents_choice():
    result = settle({"parent": "B", "a": "A", "b": "A", "c": "B"})

    assert result.counts == {"A": 2, "B": 2}
    assert result.majority_choice == "B"
    assert result.score_changes == {"parent": 3, "a": -1, "b": -1, "c": 1}


def test_zero_point_minority_stays_at_zero_but_parent_still_gains():
    result = settle(
        {"parent": "A", "ally": "A", "minority": "B"},
        {"parent": 1, "ally": 1, "minority": 0},
    )

    assert result.score_changes == {"parent": 2, "ally": 1, "minority": 0}
    assert result.scores_after == {"parent": 3, "ally": 2, "minority": 0}


def test_minority_parent_pays_the_table_and_can_collect_from_another_minority():
    result = settle({"parent": "B", "a": "A", "b": "A", "c": "B", "d": "A"})

    assert result.majority_choice == "A"
    assert result.score_changes == {"parent": 0, "a": 1, "b": 1, "c": -1, "d": 1}
    assert result.scores_after == {"parent": 1, "a": 2, "b": 2, "c": 0, "d": 2}


def test_unanswered_player_is_not_counted_or_scored():
    result = settle(
        {"parent": "A", "guest": "B"},
        {"parent": 1, "guest": 1, "offline": 4},
    )

    assert result.counts == {"A": 1, "B": 1}
    assert result.scores_after["offline"] == 4
    assert result.score_changes["offline"] == 0


def test_parent_must_be_active_and_answer_before_scoring():
    rules = MajorityPartyRules()

    with pytest.raises(ValueError, match="active player"):
        rules.settle_round(RoundInput(("guest",), "parent", {"guest": "A"}, {"guest": 1}))
    with pytest.raises(ValueError, match="must answer"):
        rules.settle_round(RoundInput(("parent", "guest"), "parent", {"guest": "A"}, {"parent": 1, "guest": 1}))


def test_rule_flags_control_zero_point_collection_and_parent_table_payment():
    rules = MajorityPartyRules(
        RuleSpec(
            parent_collects_when_minority_has_zero=False,
            minority_parent_pays_to_table=False,
        )
    )
    zero_result = rules.settle_round(
        RoundInput(
            ("parent", "ally", "minority"),
            "parent",
            {"parent": "A", "ally": "A", "minority": "B"},
            {"parent": 1, "ally": 1, "minority": 0},
        )
    )
    parent_minority = rules.settle_round(
        RoundInput(
            ("parent", "a", "b"),
            "parent",
            {"parent": "B", "a": "A", "b": "A"},
            {"parent": 1, "a": 1, "b": 1},
        )
    )

    assert zero_result.score_changes["parent"] == 1
    assert parent_minority.score_changes["parent"] == 0

from app.models import Answer, Question
from app.scoring import FixedStrategy, MajorityStrategy, MinorityStrategy


def answers() -> list[Answer]: return [Answer(player_id="a", question_id="q", choice="A"), Answer(player_id="b", question_id="q", choice="A"), Answer(player_id="c", question_id="q", choice="B")]
def test_majority() -> None: assert MajorityStrategy().calculate(Question(title="x", option_a="a", option_b="b"), answers()) == {"a": 1, "b": 1, "c": 0}
def test_minority() -> None: assert MinorityStrategy().calculate(Question(title="x", option_a="a", option_b="b", score_strategy="minority", score_config={"winner_score": 2, "loser_score": 0}), answers()) == {"a": 0, "b": 0, "c": 2}
def test_fixed() -> None: assert FixedStrategy().calculate(Question(title="x", option_a="a", option_b="b", score_strategy="fixed", score_config={"correct_answer": "B", "correct_score": 3, "wrong_score": 0}), answers()) == {"a": 0, "b": 0, "c": 3}

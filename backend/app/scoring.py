from collections import Counter
from typing import Protocol

from .models import Answer, Question


class ScoreStrategy(Protocol):
    def calculate(self, question: Question, answers: list[Answer]) -> dict[str, int]: ...


class MajorityStrategy:
    def calculate(self, question: Question, answers: list[Answer]) -> dict[str, int]:
        counts = Counter(answer.choice for answer in answers)
        if not answers or counts["A"] == counts["B"]:
            return {answer.player_id: 0 for answer in answers}
        winner = "A" if counts["A"] > counts["B"] else "B"
        return {answer.player_id: int(question.score_config.get("winner_score" if answer.choice == winner else "loser_score", 0)) for answer in answers}


class MinorityStrategy:
    def calculate(self, question: Question, answers: list[Answer]) -> dict[str, int]:
        counts = Counter(answer.choice for answer in answers)
        if not answers or not counts["A"] or not counts["B"] or counts["A"] == counts["B"]:
            return {answer.player_id: 0 for answer in answers}
        winner = "A" if counts["A"] < counts["B"] else "B"
        return {answer.player_id: int(question.score_config.get("winner_score" if answer.choice == winner else "loser_score", 0)) for answer in answers}


class FixedStrategy:
    def calculate(self, question: Question, answers: list[Answer]) -> dict[str, int]:
        correct = question.score_config.get("correct_answer", "A")
        return {answer.player_id: int(question.score_config.get("correct_score" if answer.choice == correct else "wrong_score", 0)) for answer in answers}


STRATEGIES: dict[str, ScoreStrategy] = {"majority": MajorityStrategy(), "minority": MinorityStrategy(), "fixed": FixedStrategy()}

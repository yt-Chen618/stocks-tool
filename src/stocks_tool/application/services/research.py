from stocks_tool.domain.models import CandidateScore, PlanCandidate


class ResearchService:
    def rank_candidates(self, candidates: list[PlanCandidate]) -> list[CandidateScore]:
        scored = [
            CandidateScore(candidate=candidate, composite_score=self._score(candidate))
            for candidate in candidates
        ]
        return sorted(scored, key=lambda item: item.composite_score, reverse=True)

    @staticmethod
    def _score(candidate: PlanCandidate) -> float:
        return round(
            candidate.momentum_score * 0.35
            + candidate.volatility_score * 0.25
            + candidate.liquidity_score * 0.25
            + candidate.catalyst_score * 0.15,
            4,
        )


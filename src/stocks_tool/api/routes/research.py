from fastapi import APIRouter, Depends

from stocks_tool.api.dependencies import get_research_service
from stocks_tool.application.services.research import ResearchService
from stocks_tool.domain.models import CandidateScore, ResearchRankingRequest

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/rank", response_model=list[CandidateScore])
def rank_candidates(
    request: ResearchRankingRequest,
    research_service: ResearchService = Depends(get_research_service),
) -> list[CandidateScore]:
    return research_service.rank_candidates(request.candidates)


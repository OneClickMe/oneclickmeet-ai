"""도보 코스 추천 · 교체 후보 · 지원 지역."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...v3.domain import DomainError
from ...v3.recommend import RecommendRequest as CoreRequest
from ...v3.recommend import RecommendResult, recommend, replacement_candidates
from ...v3.regions import REGIONS
from ..deps import get_search
from ..schemas import CandidateList, Ok, RecommendRequest, RegionList, RegionOut, ReplacementRequest

router = APIRouter(tags=["코스 추천"])


@router.post("/recommendations", response_model=Ok[RecommendResult], summary="도보 코스 추천")
def recommendations(body: RecommendRequest, search=Depends(get_search)):
    """기준(저장한 장소 또는 지원 지역) 반경 1km 안에서 도보 10분 이내로 이어지는 3~5곳 코스를 최대 3개 돌려줍니다.

    - 추천 실패(지원하지 않는 지역·후보 부족·외부 API 실패·결과 없음·기준 장소 없음)는 200 + `data.status`
    - '다시 추천받기'는 지금까지 받은 `courses[].signature` 를 모두 `exclude_signatures` 로 보냄
    """
    pool = [(s.place, s.source) for s in body.saved_places]
    anchor_place = body.anchor_place
    if body.anchor.type == "place" and anchor_place is None:
        anchor_place = next((p for p, _ in pool if p.place_id == body.anchor.place_id), None)
    if body.anchor.type == "place" and anchor_place is not None and anchor_place.place_id != body.anchor.place_id:
        raise DomainError("invalid_input", "anchor.place_id 와 anchor_place.place_id 가 다릅니다.")
    req = CoreRequest(anchor=body.anchor, exclude_signatures=body.exclude_signatures)
    return Ok[RecommendResult](data=recommend(req, pool, search, anchor_place))


@router.post("/recommendations/replacements", response_model=Ok[CandidateList], summary="교체 후보")
def replacements(body: ReplacementRequest, search=Depends(get_search)):
    """코스 편집 '교체': 앞·뒤 장소 양쪽에서 도보 10분 이내이고 코스에 없는 장소 (저장한 장소 먼저)."""
    if body.index >= len(body.course_places):
        raise DomainError("invalid_input", "index 가 코스 장소 수를 넘습니다.")
    pool = [(s.place, s.source) for s in body.saved_places]
    cands = replacement_candidates(body.course_places, body.index, pool, search, body.limit)
    return Ok[CandidateList](data=CandidateList(candidates=cands))


@router.get("/regions", response_model=Ok[RegionList], summary="지원 지역")
def regions():
    """추천 기준으로 고를 수 있는 지원 지역 6곳 (중심 좌표·반경은 근사값)."""
    return Ok[RegionList](data=RegionList(regions=[
        RegionOut(region_id=r.region_id, name=r.name, lat=r.lat, lng=r.lng, radius_m=r.radius_m) for r in REGIONS]))

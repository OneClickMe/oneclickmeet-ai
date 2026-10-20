"""코스 추천(R01) · 지원 지역(P01) · 카테고리 코드."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from ...v3.categories import CODES, LABELS
from ...v3.domain import Anchor, DomainError
from ...v3.recommend import RecommendRequest, recommend
from ...v3.regions import REGIONS
from ...v3.search import ExternalSearchError
from .. import convert
from ..deps import get_search
from ..errors import ApiProblem, invalid, provider_unavailable
from ..schemas import (CategoryList, CategoryOut, CourseRecommendationRequest, CourseRecommendationResponse,
                       RegionList, RegionOut)

router = APIRouter(tags=["추천"])


@router.post("/course-recommendations", response_model=CourseRecommendationResponse, summary="R01 코스 추천")
def course_recommendations(body: CourseRecommendationRequest, search=Depends(get_search)):
    """방문 순서별 카테고리(categorySequence)와 필수 장소 위치(requiredPlaceOrder)를 지켜 3~5곳 코스를 보통 2~3개
    (유효한 코스가 1개면 1개) 돌려준다. 이웃 장소 사이 추정 도보 10분 이내, 기준 반경 약 1km, 지역 자동 확장 없음.

    - 결과가 없으면 200 + `courses: []` + `reason`
    - 잘못된 형식 400, 필수 장소 정보 없음 404, 외부 검색 실패 503
    - 필수 장소의 카테고리가 그 자리와 달라도 지정 위치에 그대로 넣는다
    """
    pool, by_key = convert.saved_pool(body.saved_places, search)
    anchor_place = None
    if body.anchor.type == "PLACE":
        if body.anchor.place_id is None:
            raise invalid("PLACE 기준에는 anchor.placeId 가 필요합니다.", "anchor.placeId")
        if body.anchor_place is not None:
            if body.anchor_place.place_id != body.anchor.place_id:
                raise invalid("anchor.placeId 와 anchorPlace.placeId 가 다릅니다.", "anchorPlace.placeId")
            anchor_place = convert.saved_to_place(body.anchor_place, search)
            by_key[anchor_place.place_id] = body.anchor_place
            if all(p.place_id != anchor_place.place_id for p, _ in pool):
                pool.append((anchor_place, "couple" if body.anchor_place.source == "SHARED" else "mine"))
        else:
            key = convert.saved_key(body.anchor.place_id)
            anchor_place = next((p for p, _ in pool if p.place_id == key), None)
            if anchor_place is None:
                raise ApiProblem(404, "COMMON-0404", "RESOURCE_NOT_FOUND",
                                 "필수 장소 정보가 없습니다. anchorPlace 또는 savedPlaces 에 포함해 주세요.")
        anchor = Anchor(type="place", place_id=anchor_place.place_id)
    else:
        if not body.anchor.region_id:
            raise invalid("REGION 기준에는 anchor.regionId 가 필요합니다.", "anchor.regionId")
        anchor = Anchor(type="region", region_id=body.anchor.region_id)
    try:
        req = RecommendRequest(anchor=anchor, place_count=body.place_count, category_sequence=body.category_sequence,
                               required_place_order=body.required_place_order,
                               exclude_keys=body.exclude_candidate_keys)
    except ValidationError as e:
        msg = e.errors()[0].get("msg", "").replace("Value error, ", "")
        raise invalid(msg or "추천 조건이 올바르지 않습니다.", "categorySequence")
    try:
        res = recommend(req, pool, search, anchor_place)
    except ExternalSearchError:
        raise provider_unavailable()
    except DomainError as e:
        if e.code == "place_not_found":
            raise ApiProblem(404, "COMMON-0404", "RESOURCE_NOT_FOUND", e.message)
        raise
    return convert.recommendation(res, by_key)


@router.get("/regions", response_model=RegionList, summary="P01 지원 지역")
def regions():
    """데모 지원 지역 6곳 (중심 좌표·반경은 근사값, 경계는 후속 확정)."""
    return RegionList(items=[RegionOut(region_id=r.region_id, name=r.name, latitude=r.lat, longitude=r.lng,
                                       radius_meters=r.radius_m) for r in REGIONS])


@router.get("/categories", response_model=CategoryList, summary="추천 카테고리 코드")
def categories():
    """categorySequence 에 쓰는 코드 7개 (v2 확정)."""
    return CategoryList(items=[CategoryOut(code=c, label=LABELS[c]) for c in CODES])

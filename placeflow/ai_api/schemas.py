"""AI 서버 요청·응답 모델. 결과 모델(ResolveResult·RecommendResult·Place)은 placeflow.v3 의 것을 그대로 씁니다."""
from __future__ import annotations

from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

from ..v3.domain import Anchor, Place
from ..v3.recommend import Cand

T = TypeVar("T")

MAX_SAVED_PLACES = 500
MAX_SAVED_IDS = 2000


# ------------------------------------------------------------------ 공통 응답 봉투
class ErrorBody(BaseModel):
    code: str = Field(..., examples=["invalid_input"])
    message: str = Field(..., description="사용자에게 그대로 보여줘도 되는 한국어 문장")


class Ok(BaseModel, Generic[T]):
    ok: Literal[True] = True
    data: T


class Err(BaseModel):
    ok: Literal[False] = False
    error: ErrorBody


# ------------------------------------------------------------------ 요청
class SavedPlaceIn(BaseModel):
    """백엔드가 보내는 사용자의 저장 장소 1곳 (AI 서버는 저장하지 않음)."""
    place: Place
    source: Literal["mine", "couple"] = Field("mine", description="mine=내 보관함, couple=공동 보관함")


class ResolveRequest(BaseModel):
    """링크·캡션 인식. 스크린샷은 multipart 엔드포인트(/places/resolve/screenshot)를 씁니다."""
    type: Literal["link", "text"] = Field(..., description="link: url 필수 / text: note 필수")
    url: Optional[str] = Field(None, max_length=4000,
                               description="링크 또는 앱 '공유 → 복사' 문구 전체 (첫 http 링크를 씀)")
    note: Optional[str] = Field(None, max_length=20000, description="함께 붙여넣은 캡션·메모")
    saved_place_ids: list[str] = Field(default_factory=list, max_length=MAX_SAVED_IDS,
                                       description="이미 저장한 place_id → 후보에 already_saved=true")


class RecommendRequest(BaseModel):
    anchor: Anchor
    anchor_place: Optional[Place] = Field(None, description="anchor.type=place 일 때 기준 장소. 없으면 saved_places 에서 찾음")
    saved_places: list[SavedPlaceIn] = Field(default_factory=list, max_length=MAX_SAVED_PLACES)
    exclude_signatures: list[str] = Field(default_factory=list, max_length=200,
                                          description="'다시 추천받기': 앞에서 받은 courses[].signature 전부")


class ReplacementRequest(BaseModel):
    course_places: list[Place] = Field(..., min_length=1, max_length=5, description="지금 코스의 장소들 (순서대로)")
    index: int = Field(..., ge=0, description="교체할 장소의 위치 (0부터)")
    saved_places: list[SavedPlaceIn] = Field(default_factory=list, max_length=MAX_SAVED_PLACES)
    limit: int = Field(8, ge=1, le=20)


class NearbyRequest(BaseModel):
    place: Place
    saved_places: list[SavedPlaceIn] = Field(default_factory=list, max_length=MAX_SAVED_PLACES)
    limit: int = Field(3, ge=1, le=10)


# ------------------------------------------------------------------ 응답 (v3 결과 모델 외)
class CandidateList(BaseModel):
    candidates: list[Cand]


class RegionOut(BaseModel):
    region_id: str
    name: str
    lat: float
    lng: float
    radius_m: int


class RegionList(BaseModel):
    regions: list[RegionOut]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    workflow_version: str
    search_provider: str
    extractor: str
    ocr: str
    ocr_ready: bool
    auth_required: bool

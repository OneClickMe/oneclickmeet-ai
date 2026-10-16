"""데이터 모델.

- ExtractedPlace / ExtractionResult : LLM(또는 휴리스틱 추출기)이 내놓는 1차 결과
- PlaceRecord                      : 저장되는 최종 메타데이터 (schema/place_record.schema.json 의 원본)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from . import taxonomy

SCHEMA_VERSION = "0.2.0"

PrimaryCategory = Literal[tuple(taxonomy.PRIMARY.keys())]  # type: ignore[valid-type]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SourceType(str, Enum):
    instagram_link = "instagram_link"
    naver_blog = "naver_blog"
    naver_place = "naver_place"
    naver_short = "naver_short"
    web_link = "web_link"
    image = "image"
    text = "text"


class Status(str, Enum):
    complete = "complete"                  # 바로 저장해도 됨
    needs_review = "needs_review"          # 저장하되 사용자 확인 권장
    needs_user_input = "needs_user_input"  # 정보 부족 → 캡쳐/캡션 추가 요청
    failed = "failed"


# ---------------------------------------------------------------- 1차 추출 결과
class Menu(BaseModel):
    name: str
    price: Optional[int] = Field(None, description="원 단위 정수")


class ExtractedPlace(BaseModel):
    """콘텐츠 한 건에서 찾은 장소 하나. 확실하지 않은 값은 null."""

    name: str = Field(..., description="상호명/장소명. 지점명은 branch 로 분리")
    branch: Optional[str] = Field(None, description="지점명 예: 성수점")
    address_hint: Optional[str] = Field(None, description="본문에 적힌 주소 그대로")
    region_hint: Optional[str] = Field(None, description="동네/지역 단서 예: 성수, 연남동, 제주 애월")
    phone: Optional[str] = None
    primary_category: PrimaryCategory = "other"  # type: ignore[valid-type]
    sub_category: Optional[str] = None
    tags: list[str] = Field(default_factory=list, description="택소노미 태그 목록에서만")
    free_tags: list[str] = Field(default_factory=list, description="목록에 없는 특징(해시태그 등), 최대 5개")
    signature_menus: list[Menu] = Field(default_factory=list)
    price_level: Optional[int] = Field(None, ge=1, le=4)
    price_text: Optional[str] = None
    opening_hours_text: Optional[str] = Field(None, description="영업시간 원문 그대로(요일별이면 전부). 예: '월-금 11:30-21:00 / 토,일 12:00-22:00'")
    closed_days_text: Optional[str] = None
    break_time_text: Optional[str] = Field(None, description="브레이크타임 원문 예: '15:00-17:00'")
    last_order_text: Optional[str] = Field(None, description="라스트오더 원문 예: '21:00'")
    reservation_text: Optional[str] = None
    reservation_method: Optional[Literal["naver", "catchtable", "phone", "dm", "walk_in", "other"]] = None
    est_cost_per_person: Optional[int] = Field(None, description="1인 예상 비용(원). 메뉴 가격 근거가 있을 때만")
    rating: Optional[float] = Field(None, ge=0, le=5, description="화면에 보이는 평점")
    review_count: Optional[int] = None
    nearest_station_text: Optional[str] = Field(None, description="예: '압구정로데오역 5번 출구에서 534m'")
    parking_text: Optional[str] = None
    amenities: list[str] = Field(default_factory=list, description="편의시설 예: 단체 이용 가능, 무선 인터넷")
    stay_minutes_hint: Optional[int] = Field(None, description="본문에 '2시간 소요' 등 근거가 있을 때만")
    indoor: Optional[bool] = Field(None, description="실내면 true, 실외면 false, 모르면 null")
    summary: Optional[str] = Field(None, description="커플 데이트 관점 한두 문장 요약")
    highlights: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list, description="웨이팅, 주차 불가 등 주의점")
    evidence: list[str] = Field(default_factory=list, description="근거가 된 원문 구절(짧게)")
    confidence: float = Field(0.5, ge=0, le=1, description="이 장소 정보 전체에 대한 확신도")


class ExtractionResult(BaseModel):
    places: list[ExtractedPlace] = Field(default_factory=list)
    is_place_content: bool = Field(True, description="장소와 무관한 콘텐츠면 false")
    notes: Optional[str] = None


# ---------------------------------------------------------------- 최종 레코드
class SourceInfo(BaseModel):
    type: SourceType
    input_kind: Literal["link", "image", "text"]
    url: Optional[str] = None
    final_url: Optional[str] = None
    file_name: Optional[str] = None
    fetch_status: Literal["ok", "blocked", "error", "skipped"] = "skipped"
    fetched_at: str = Field(default_factory=_now)


class GeoPoint(BaseModel):
    lat: float
    lng: float


class Address(BaseModel):
    road: Optional[str] = None
    jibun: Optional[str] = None
    sido: Optional[str] = None
    sigungu: Optional[str] = None
    dong: Optional[str] = None


class ExternalIds(BaseModel):
    naver_place_id: Optional[str] = None
    kakao_place_id: Optional[str] = None


class PlaceInfo(BaseModel):
    name: str
    branch: Optional[str] = None
    address: Address = Field(default_factory=Address)
    location: Optional[GeoPoint] = None
    phone: Optional[str] = None
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    map_url: Optional[str] = None
    provider_category: Optional[str] = Field(None, description="지도 API가 준 원본 카테고리 문자열")


class Classification(BaseModel):
    primary_category: PrimaryCategory  # type: ignore[valid-type]
    primary_label: str
    sub_category: Optional[str] = None
    sub_label: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    free_tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _only_known_tags(cls, v: list[str]) -> list[str]:
        return [t for t in dict.fromkeys(v) if t in taxonomy.ALL_TAGS]


class TimeRange(BaseModel):
    open: str = Field(..., pattern=r"^([0-3]\d|4[0-7]):[0-5]\d$", description="HH:MM")
    close: str = Field(..., pattern=r"^([0-3]\d|4[0-7]):[0-5]\d$",
                       description="HH:MM, 자정 넘으면 24 이상 (예: 26:00 = 다음날 02:00)")


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class WeeklyHours(BaseModel):
    """구조화된 영업시간. 요일 키가 없으면 '정보 없음', 빈 리스트면 '휴무'."""

    days: dict[str, list[TimeRange]] = Field(default_factory=dict)
    breaks: dict[str, list[TimeRange]] = Field(default_factory=dict)
    last_order: dict[str, str] = Field(default_factory=dict)
    closed_days: list[str] = Field(default_factory=list)
    partial: bool = Field(False, description="일부 요일/시작시간만 알려진 경우")
    earliest_open: Optional[str] = Field(None, description="'17:00에 영업 시작'처럼 시작 시각만 알 때")
    raw: Optional[str] = None


class FieldSource(BaseModel):
    source: str = Field(..., description="ocr | link | llm | heuristic | geo:kakao | default | user …")
    collected_at: str = Field(default_factory=_now)
    confidence: Optional[float] = Field(None, ge=0, le=1)


class Details(BaseModel):
    signature_menus: list[Menu] = Field(default_factory=list)
    price_level: Optional[int] = Field(None, ge=1, le=4)
    price_text: Optional[str] = None
    est_cost_per_person: Optional[int] = Field(None, description="1인 예상 비용(원)")
    opening_hours_text: Optional[str] = None
    closed_days_text: Optional[str] = None
    opening_hours: Optional[WeeklyHours] = None
    reservation_text: Optional[str] = None
    reservation_method: Optional[str] = None
    reservation_required: Optional[bool] = None
    waiting_level: Optional[Literal["none", "some", "long"]] = None
    stay_minutes: Optional[int] = Field(None, description="평균 체류시간(분)")
    indoor: Optional[bool] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    nearest_station: Optional[str] = None
    parking: Optional[str] = None
    amenities: list[str] = Field(default_factory=list)


class Content(BaseModel):
    summary: Optional[str] = None
    highlights: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    raw_excerpt: Optional[str] = Field(None, description="원문 일부(개인정보 마스킹 후, 최대 1000자)")


class Confidence(BaseModel):
    overall: float = Field(..., ge=0, le=1)
    extraction: float = Field(..., ge=0, le=1)
    geo_match: Optional[float] = Field(None, ge=0, le=1)


class PlaceRecord(BaseModel):
    schema_version: str = SCHEMA_VERSION
    record_id: str
    dedupe_key: str
    status: Status
    review_reasons: list[str] = Field(default_factory=list)
    sources: list[SourceInfo]
    place: PlaceInfo
    classification: Classification
    details: Details = Field(default_factory=Details)
    content: Content = Field(default_factory=Content)
    confidence: Confidence
    embedding_text: str = Field(..., description="추천 단계에서 임베딩할 요약 문자열")
    provenance: dict[str, FieldSource] = Field(default_factory=dict, description="필드별 출처·수집일·신뢰도")
    missing_fields: list[str] = Field(default_factory=list,
                                      description="코스 추천에 필요한데 비어 있는 필드 (opening_hours, location, est_cost_per_person)")
    visited: bool = Field(False, description="다녀온 곳 (코스 추천에서 '새로운 곳' 가중치)")
    extractor: str = Field(..., description="사용한 추출기/모델 식별자")
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    @model_validator(mode="after")
    def _upgrade_v01(self):
        """v0.1 레코드: 영업시간 원문만 있으면 구조화하고, 비어 있는 핵심 정보를 다시 계산."""
        d = self.details
        if d.opening_hours is None and (d.opening_hours_text or d.closed_days_text):
            from .hours import parse_hours

            d.opening_hours = parse_hours(" / ".join(x for x in (d.opening_hours_text, d.closed_days_text) if x))
        if self.schema_version < "0.2.0" and not self.missing_fields:
            miss = []
            if d.opening_hours is None or d.opening_hours.partial:
                miss.append("opening_hours")
            if self.place.location is None:
                miss.append("location")
            if d.est_cost_per_person is None:
                miss.append("est_cost_per_person")
            self.missing_fields = miss
        return self


class PipelineOutput(BaseModel):
    """파이프라인 한 번 실행 결과 (레코드 0~N개 + 실행 추적)."""

    status: Status
    records: list[PlaceRecord] = Field(default_factory=list)
    message: Optional[str] = Field(None, description="사용자에게 보여줄 안내 (예: 캡쳐를 올려주세요)")
    trace: list[dict] = Field(default_factory=list)

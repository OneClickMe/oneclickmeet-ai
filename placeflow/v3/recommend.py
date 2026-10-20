"""AI 코스 추천 엔진 v2 (TRD R01: 방문 순서별 카테고리 + 필수 장소 위치).

입력  anchor           장소 1곳(필수 장소) 또는 지원 지역 1곳
      place_count      전체 장소 수 3~5
      category_sequence 방문 순서별 카테고리 코드 (원소 수 = place_count)
      required_place_order  필수 장소의 방문 위치 1..place_count (장소 기준일 때만, 지역 기준은 생략)
규칙  - 기준 반경 약 1km 안의 후보만 (내 보관함 + 공동 보관함 + 외부 후보)
      - 각 자리에는 그 자리 카테고리의 장소만. 필수 장소는 지정한 자리에 고정
        (필수 장소의 카테고리가 그 자리와 달라도 그대로 넣음 — 경고 없음)
      - 이웃한 장소 사이 추정 도보 10분 이내 (좌표 기반 추정, 실제 경로 아님)
      - 서로 다른 코스 최대 3개 (보통 2~3개, 유효한 코스가 1개면 1개). 저장 장소 우선
      - 지역은 자동으로 넓히지 않음. 외부 검색이 실패하면 ExternalSearchError (→ API 503)
결과 courses 가 비면 reason: INSUFFICIENT_PLACES | UNSUPPORTED_REGION | NO_MORE_COURSES(다시 추천에서 더 없음)
"""
from __future__ import annotations

import hashlib
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .categories import CODES, LABELS, CategoryCode
from .domain import Anchor, Course, CourseStop, DomainError, MAX_STOPS, MIN_STOPS, Place
from .regions import Region, get_region, region_of
from .search import ExternalSearchError, SearchProvider
from .walking import ANCHOR_RADIUS_M, MAX_LEG_MIN, distance_m, walk_minutes

MAX_EXTERNAL_PER_CODE = 12
BEAM = 3000
NEARBY_CODES = ("ACTIVITY", "CULTURE", "WALK", "CAFE")

Source = Literal["mine", "couple", "external"]
Reason = Literal["INSUFFICIENT_PLACES", "UNSUPPORTED_REGION", "NO_MORE_COURSES"]


class Cand(BaseModel):
    place: Place
    source: Source


class WalkingLeg(BaseModel):
    from_visit_order: int
    to_visit_order: int
    estimated_minutes: int


class RecommendedPlace(BaseModel):
    visit_order: int
    place: Place
    source: Source
    is_anchor: bool = False
    slot_category: str = Field(..., description="이 자리에 요청한 카테고리 코드")
    walk_from_prev_min: Optional[int] = None


class RecommendedCourse(BaseModel):
    candidate_key: str = Field(..., description="코스 구분 키 (같은 구성이면 같은 값). 영구 courseId 아님")
    title: str
    places: list[RecommendedPlace]
    walking_legs: list[WalkingLeg]
    total_walk_min: int
    saved_count: int
    external_count: int
    score: float
    reasons: list[str] = Field(default_factory=list)


class Step(BaseModel):
    key: str
    label: str
    done: bool = False


class RecommendRequest(BaseModel):
    anchor: Anchor
    place_count: int = Field(..., ge=MIN_STOPS, le=MAX_STOPS)
    category_sequence: list[CategoryCode] = Field(..., min_length=MIN_STOPS, max_length=MAX_STOPS)
    required_place_order: Optional[int] = Field(None, ge=1, le=MAX_STOPS)
    exclude_keys: list[str] = Field(default_factory=list, description="'다시 추천받기': 앞에서 받은 candidate_key 들")
    max_courses: int = Field(3, ge=1, le=3)

    @model_validator(mode="after")
    def _check(self):
        if len(self.category_sequence) != self.place_count:
            raise ValueError("categorySequence 원소 수는 placeCount 와 같아야 합니다.")
        if self.anchor.type == "place":
            if self.required_place_order is None:
                raise ValueError("장소 기준 추천에는 requiredPlaceOrder 가 필요합니다.")
            if self.required_place_order > self.place_count:
                raise ValueError("requiredPlaceOrder 는 1~placeCount 범위여야 합니다.")
        elif self.required_place_order is not None:
            raise ValueError("지역 기준 추천에서는 requiredPlaceOrder 를 보내지 않습니다.")
        return self


class RecommendResult(BaseModel):
    courses: list[RecommendedCourse] = Field(default_factory=list)
    reason: Optional[Reason] = None
    walking_time_method: Literal["COORDINATE_ESTIMATE"] = "COORDINATE_ESTIMATE"
    region: Optional[dict] = None
    candidates_count: int = 0
    steps: list[Step] = Field(default_factory=list)
    message: Optional[str] = None


STEP_DEFS = [("candidates", "근처 후보 찾는 중"), ("walking", "도보 거리 확인 중"), ("compose", "코스 구성 중")]
MESSAGES = {
    "UNSUPPORTED_REGION": "아직 지원하지 않는 지역이에요. 지금은 연남·서촌·혜화·잠실·성신여대역·한성대입구역에서 코스를 추천해요.",
    "INSUFFICIENT_PLACES": "조건(카테고리 순서·필수 장소 위치)에 맞게 걸어서 이을 장소가 부족해요. 카테고리를 바꾸거나 장소를 더 저장해 보세요. 지역은 자동으로 넓히지 않아요.",
    "NO_MORE_COURSES": "같은 조건으로 더 추천할 코스가 없어요. 카테고리 순서를 바꿔 보세요.",
}


def _steps(n_done: int) -> list[Step]:
    return [Step(key=k, label=l, done=i < n_done) for i, (k, l) in enumerate(STEP_DEFS)]


def _region_dict(r: Optional[Region]) -> Optional[dict]:
    return {"region_id": r.region_id, "name": r.name} if r else None


def _empty(reason: str, n_done: int, region: Optional[Region] = None, count: int = 0) -> RecommendResult:
    return RecommendResult(reason=reason, steps=_steps(n_done), message=MESSAGES[reason], candidates_count=count,
                           region=_region_dict(region))


def signature_of(place_ids: list[str]) -> str:
    """방문 순서까지 포함한 코스 구성 문자열."""
    return ">".join(place_ids)


def candidate_key_of(place_ids: list[str]) -> str:
    return "crs_" + hashlib.sha1(signature_of(place_ids).encode("utf-8")).hexdigest()[:10]


def course_title(region: Region, sequence: list[str]) -> str:
    return f"{region.name} {'·'.join(dict.fromkeys(LABELS[c] for c in sequence))} 코스"


# ------------------------------------------------------------------ 후보 수집
def gather_candidates(center: tuple[float, float], codes: set[str], user_pool: list[tuple[Place, str]],
                      search: SearchProvider, radius_m: int = ANCHOR_RADIUS_M,
                      exclude_ids: frozenset = frozenset()) -> dict[str, list[Cand]]:
    """카테고리 코드별 후보 (저장 장소 먼저, 외부는 가까운 순 최대 12곳). 외부 검색 실패는 ExternalSearchError 전파."""
    by_code: dict[str, list[Cand]] = {c: [] for c in codes}
    saved: list[Cand] = []
    for p, src in user_pool:
        if p.place_id in exclude_ids or distance_m(center, p.pos) > radius_m:
            continue
        c = Cand(place=p, source="couple" if src == "couple" else "mine")
        saved.append(c)
        if p.category_code in by_code:
            by_code[p.category_code].append(c)
    for code in codes:
        ext = []
        for p in search.nearby(center[0], center[1], radius_m, code=code, limit=40):
            if p.place_id in exclude_ids or any(s.place.place_id == p.place_id for s in saved):
                continue
            # 저장 장소와 같은 가게(이름 같고 80m 이내)는 중복
            if any(s.place.name.replace(" ", "") == p.name.replace(" ", "") and distance_m(s.place.pos, p.pos) < 80
                   for s in saved):
                continue
            ext.append(p)
        ext.sort(key=lambda p: distance_m(center, p.pos))
        by_code[code] += [Cand(place=p, source="external") for p in ext[:MAX_EXTERNAL_PER_CODE]]
    return by_code


# ------------------------------------------------------------------ 탐색 (자리 채우기)
def _node_score(c: Cand) -> float:
    return 5.0 if c.source != "external" else 0.0


def _fill_slots(slots: list[list[int]], nodes: list[Cand], anchor_idx: Optional[int],
                anchor_pos: Optional[int]) -> list[tuple[float, list[int], list[int]]]:
    """slots[i] = i번째 자리에 넣을 수 있는 노드 번호들. 이웃 도보 10분 이내, 중복 없음.
    반환: (점수, 경로, 구간 도보분) — 점수 높은 순."""
    walk_cache: dict[tuple[int, int], int] = {}

    def w(a: int, b: int) -> int:
        k = (a, b) if a < b else (b, a)
        if k not in walk_cache:
            walk_cache[k] = walk_minutes(nodes[a].place.pos, nodes[b].place.pos)
        return walk_cache[k]

    beam: list[tuple[float, list[int], list[int]]] = [(0.0, [], [])]
    for i, options in enumerate(slots):
        nxt = []
        for sc, path, legs in beam:
            for n in options:
                if n in path:
                    continue
                leg = w(path[-1], n) if path else None
                if leg is not None and leg > MAX_LEG_MIN:
                    continue
                # 필수 장소 자리 앞이면, 남은 칸 수 안에 필수 장소까지 걸어갈 수 있어야 함 (가지치기)
                if anchor_idx is not None and i < anchor_pos and n != anchor_idx:
                    if w(n, anchor_idx) > (MAX_LEG_MIN + 1) * (anchor_pos - i):
                        continue
                new_legs = legs + ([leg] if leg is not None else [])
                nxt.append((sc + _node_score(nodes[n]) - 0.12 * (leg or 0), path + [n], new_legs))
        nxt.sort(key=lambda x: -x[0])
        beam = nxt[:BEAM]
        if not beam:
            return []
    return beam


def _reasons(path: list[Cand], legs: list[int]) -> list[str]:
    saved = sum(1 for c in path if c.source != "external")
    r = []
    if saved:
        r.append(f"저장한 장소 {saved}곳 포함")
    if legs:
        r.append(f"장소 사이 최대 도보 {max(legs)}분 (추정)")
    return r


def recommend(req: RecommendRequest, user_pool: list[tuple[Place, str]], search: SearchProvider,
              anchor_place: Optional[Place] = None) -> RecommendResult:
    """외부 검색 실패는 ExternalSearchError, 기준 장소 없음은 DomainError('place_not_found')."""
    # 0) 기준 확인
    if req.anchor.type == "place":
        if anchor_place is None:
            raise DomainError("place_not_found", "기준 장소를 찾을 수 없어요. 보관함에서 다시 골라 주세요.")
        center = anchor_place.pos
        region = region_of(*center)
    else:
        region = get_region(req.anchor.region_id or "")
        center = (region.lat, region.lng) if region else None
    if region is None:
        return _empty("UNSUPPORTED_REGION", 0)

    seq = list(req.category_sequence)
    anchor_pos = (req.required_place_order - 1) if anchor_place is not None else None
    codes = {c for i, c in enumerate(seq) if i != anchor_pos}

    # 1) 근처 후보 찾기
    exclude = frozenset([anchor_place.place_id]) if anchor_place else frozenset()
    by_code = gather_candidates(center, codes, user_pool, search, exclude_ids=exclude)  # ExternalSearchError 전파
    nodes: list[Cand] = []
    index: dict[str, int] = {}

    def node_of(c: Cand) -> int:
        if c.place.place_id not in index:
            index[c.place.place_id] = len(nodes)
            nodes.append(c)
        return index[c.place.place_id]

    anchor_idx = None
    if anchor_place is not None:
        src = next((s for p, s in user_pool if p.place_id == anchor_place.place_id), "mine")
        anchor_idx = node_of(Cand(place=anchor_place, source="couple" if src == "couple" else "mine"))
    slot_nodes: dict[str, list[int]] = {code: [node_of(c) for c in lst] for code, lst in by_code.items()}
    slots = [[anchor_idx] if i == anchor_pos else slot_nodes.get(code, []) for i, code in enumerate(seq)]
    if any(not s for s in slots):
        return _empty("INSUFFICIENT_PLACES", 2, region, len(nodes))

    # 2)·3) 도보 거리 확인 + 코스 구성
    ranked = _fill_slots(slots, nodes, anchor_idx, anchor_pos if anchor_pos is not None else 0)
    if not ranked:
        return _empty("INSUFFICIENT_PLACES", 3, region, len(nodes))
    excluded = set(req.exclude_keys)
    chosen: list[tuple[float, list[int], list[int]]] = []
    skipped_by_exclude = False
    for max_overlap in (1, 2):  # 기준 외 겹침 1곳 이하 먼저, 모자라면 2곳까지
        for sc, p, lg in ranked:
            if len(chosen) >= req.max_courses:
                break
            key = candidate_key_of([nodes[i].place.place_id for i in p])
            if key in excluded:
                skipped_by_exclude = True
                continue
            if any(p == q for _, q, _ in chosen):
                continue
            others = set(i for i in p if i != anchor_idx)
            if any(len(others & set(i for i in q if i != anchor_idx)) > max_overlap for _, q, _ in chosen):
                continue
            chosen.append((sc, p, lg))
    if not chosen:
        return _empty("NO_MORE_COURSES" if skipped_by_exclude else "INSUFFICIENT_PLACES", 3, region, len(nodes))

    title = course_title(region, seq)
    courses = []
    for sc, p, lg in chosen:
        places = [RecommendedPlace(visit_order=k + 1, place=nodes[i].place, source=nodes[i].source,
                                   is_anchor=(i == anchor_idx), slot_category=seq[k],
                                   walk_from_prev_min=lg[k - 1] if k else None) for k, i in enumerate(p)]
        courses.append(RecommendedCourse(
            candidate_key=candidate_key_of([nodes[i].place.place_id for i in p]), title=title, places=places,
            walking_legs=[WalkingLeg(from_visit_order=k + 1, to_visit_order=k + 2, estimated_minutes=m)
                          for k, m in enumerate(lg)],
            total_walk_min=sum(lg), saved_count=sum(1 for i in p if nodes[i].source != "external"),
            external_count=sum(1 for i in p if nodes[i].source == "external"), score=round(sc, 3),
            reasons=_reasons([nodes[i] for i in p], lg)))
    return RecommendResult(courses=courses, steps=_steps(3), candidates_count=len(nodes), region=_region_dict(region))


# ------------------------------------------------------------------ 코스 편집 보조
def replacement_candidates(course_places: list[Place], index: int, user_pool: list[tuple[Place, str]],
                           search: SearchProvider, limit: int = 8, code: Optional[str] = None) -> list[Cand]:
    """'장소 교체': 앞뒤 장소와 모두 도보 10분 이내이고 코스에 없는 후보.
    code 를 주지 않으면 교체할 장소와 같은 카테고리. 저장한 장소 먼저."""
    target = course_places[index]
    code = code or target.category_code
    in_course = frozenset(p.place_id for p in course_places)
    neighbors = [course_places[i] for i in (index - 1, index + 1) if 0 <= i < len(course_places)]
    if code:
        pool = gather_candidates(target.pos, {code}, user_pool, search, exclude_ids=in_course)[code]
    else:
        pool = [Cand(place=p, source="external") for p in search.nearby(target.lat, target.lng, ANCHOR_RADIUS_M)
                if p.place_id not in in_course]
    ok = [c for c in pool if all(walk_minutes(n.pos, c.place.pos) <= MAX_LEG_MIN for n in neighbors)]
    ok.sort(key=lambda c: (c.source == "external", sum(walk_minutes(n.pos, c.place.pos) for n in neighbors)))
    return ok[:limit]


def nearby_places(place: Place, user_pool: list[tuple[Place, str]], search: SearchProvider,
                  limit: int = 3) -> list[Cand]:
    """장소 상세 '주변 놀거리': 도보 10분 이내의 놀거리·전시·산책·카페 (저장한 장소 먼저).
    외부 검색이 실패하면 저장 장소만."""
    try:
        by_code = gather_candidates(place.pos, set(NEARBY_CODES), user_pool, search,
                                    exclude_ids=frozenset([place.place_id]))
        pool = [c for code in NEARBY_CODES for c in by_code[code]]
    except ExternalSearchError:
        pool = [Cand(place=p, source="couple" if s == "couple" else "mine") for p, s in user_pool
                if p.place_id != place.place_id and p.category_code in NEARBY_CODES]
    seen, ok = set(), []
    for c in pool:
        if c.place.place_id not in seen and walk_minutes(place.pos, c.place.pos) <= MAX_LEG_MIN:
            seen.add(c.place.place_id)
            ok.append(c)
    ok.sort(key=lambda c: (c.source == "external", walk_minutes(place.pos, c.place.pos)))
    return ok[:limit]


def to_course_draft(rec: RecommendedCourse, owner_id: str, anchor: Anchor, title: Optional[str] = None) -> Course:
    """'이 코스 선택' → 코스 상세 드래프트 (아직 저장 전, 항목 없음)."""
    stops = [CourseStop(place=s.place, is_anchor=s.is_anchor, external=s.source == "external") for s in rec.places]
    return Course(owner_id=owner_id, title=title or rec.title, anchor=anchor, stops=stops)

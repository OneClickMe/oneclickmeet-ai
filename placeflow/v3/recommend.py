"""AI 코스 추천 엔진 (V3: 도보 데이트 코스).

입력  기준 = 장소 1곳(보관함) 또는 지원 지역 1곳
규칙  - 기준 반경 약 1km 안의 후보만 (내 보관함 + 공동 보관함 + 외부 추천)
      - 장소 사이는 걸어서 10분 이내 (예상 도보시간)
      - 코스 1개 = 장소 3~5곳, 기준 장소는 반드시 포함 (위치는 어디든 가능)
      - 결과는 서로 겹치지 않는 코스 최대 3개. '다시 추천받기'는 직전 코스를 빼고 다시 계산
      - 지역은 자동으로 넓히지 않음. 외부 검색이 실패하면 이번에는 코스를 만들지 않음
상태  ok | unsupported_region | external_api_failed | not_enough_candidates | no_result | anchor_not_found

점수 (높을수록 좋음)
  저장한 장소 +5/곳 · 업종 다양성 +2.5/종류 · 같은 업종 연속 -4 · 맛집 3곳 이상/술집 2곳 이상 감점
  맛집이나 카페 포함 +2 · 총 도보시간 -0.12/분 · 4곳 +2 (업종 다양성은 4종까지만 가점)
"""
from __future__ import annotations

from collections import deque
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .domain import Anchor, Course, CourseStop, MAX_STOPS, MIN_STOPS, Place
from .regions import Region, get_region, region_of
from .search import ExternalSearchError, SearchProvider
from .walking import ANCHOR_RADIUS_M, MAX_LEG_MIN, distance_m, walk_minutes

# 외부 추천 후보를 모을 때 '지역명 + 검색어' 조합 (네이버 지역검색은 한 번에 5건)
EXTERNAL_QUERIES = ["맛집", "카페", "디저트", "술집", "산책", "공원", "소품샵", "전시", "놀거리", "공방"]
MAX_EXTERNAL = 30
BEAM = 1500
FUN_CATS = {"activity", "culture", "nature", "shopping", "cafe"}

Source = Literal["mine", "couple", "external"]


class Cand(BaseModel):
    place: Place
    source: Source


class RecommendedStop(BaseModel):
    order: int
    place: Place
    source: Source
    is_anchor: bool = False
    external: bool = False
    walk_from_prev_min: Optional[int] = None


class RecommendedCourse(BaseModel):
    signature: str = Field(..., description="코스 식별용 (장소 ID 정렬 결합). '다시 추천받기' 때 exclude 로 보냄")
    stops: list[RecommendedStop]
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
    exclude_signatures: list[str] = Field(default_factory=list, description="이전에 보여준 코스 signature 들")
    max_courses: int = Field(3, ge=1, le=3)


class RecommendResult(BaseModel):
    status: Literal["ok", "unsupported_region", "external_api_failed", "not_enough_candidates", "no_result",
                    "anchor_not_found"]
    courses: list[RecommendedCourse] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    region: Optional[dict] = None
    candidates_count: int = 0
    message: Optional[str] = None


STEP_DEFS = [("candidates", "근처 후보 찾는 중"), ("walking", "도보 거리 확인 중"), ("compose", "코스 구성 중")]
MESSAGES = {
    "unsupported_region": "아직 지원하지 않는 지역이에요. 지금은 연남·서촌·혜화·잠실·성신여대역·한성대입구역에서 코스를 추천해요.",
    "external_api_failed": "후보를 가져오지 못했어요. 직접 검색은 계속 쓸 수 있어요. 이번에는 코스를 만들지 않아요.",
    "not_enough_candidates": "걸어서 갈 수 있는 후보가 3곳 미만이라 코스를 내놓지 않아요. 지역은 자동으로 넓히지 않아요.",
    "no_result": "조건에 맞는 코스를 찾지 못했어요. 조건을 바꿔 다시 추천받아 보세요. 지역은 자동으로 넓히지 않아요.",
    "anchor_not_found": "기준 장소를 찾을 수 없어요. 보관함에서 다시 골라 주세요.",
}


def _steps(n_done: int) -> list[Step]:
    return [Step(key=k, label=l, done=i < n_done) for i, (k, l) in enumerate(STEP_DEFS)]


def _fail(status: str, n_done: int, region: Optional[Region] = None, count: int = 0) -> RecommendResult:
    return RecommendResult(status=status, steps=_steps(n_done), message=MESSAGES[status], candidates_count=count,
                           region={"region_id": region.region_id, "name": region.name} if region else None)


def signature_of(place_ids: list[str]) -> str:
    return "|".join(sorted(place_ids))


# ------------------------------------------------------------------ 후보 수집
def gather_candidates(center: tuple[float, float], region: Region, user_pool: list[tuple[Place, str]],
                      search: SearchProvider, radius_m: int = ANCHOR_RADIUS_M,
                      exclude_ids: frozenset = frozenset()) -> list[Cand]:
    """반경 안의 저장 장소 + 외부 검색 장소. 외부 검색 실패 시 ExternalSearchError 를 그대로 올림."""
    out: dict[str, Cand] = {}
    for p, src in user_pool:
        if p.place_id not in exclude_ids and distance_m(center, p.pos) <= radius_m:
            out[p.place_id] = Cand(place=p, source="couple" if src == "couple" else "mine")
    externals: dict[str, Place] = {}
    for w in EXTERNAL_QUERIES:
        for p in search.search(f"{region.area_query} {w}", 5):  # ExternalSearchError 전파
            externals.setdefault(p.place_id, p)
    ext = []
    for p in externals.values():
        if p.place_id in out or p.place_id in exclude_ids or distance_m(center, p.pos) > radius_m:
            continue
        # 저장 장소와 같은 가게(이름 같고 80m 이내)는 중복으로 보고 제외
        if any(c.place.name.replace(" ", "") == p.name.replace(" ", "") and distance_m(c.place.pos, p.pos) < 80
               for c in out.values()):
            continue
        ext.append(p)
    ext.sort(key=lambda p: distance_m(center, p.pos))
    for p in ext[:MAX_EXTERNAL]:
        out[p.place_id] = Cand(place=p, source="external")
    return list(out.values())


# ------------------------------------------------------------------ 점수
def _node_score(c: Cand) -> float:
    return 5.0 if c.source in ("mine", "couple") else 0.0


def _path_score(path: list[Cand], legs: list[int]) -> float:
    cats = [c.place.category for c in path]
    s = sum(_node_score(c) for c in path)
    s += min(len(set(cats)), 4) * 2.5
    s -= sum(4 for a, b in zip(cats, cats[1:]) if a == b)
    s -= max(0, cats.count("restaurant") - 2) * 3 + max(0, cats.count("bar") - 1) * 2
    if "restaurant" in cats or "cafe" in cats:
        s += 2
    s -= sum(legs) * 0.12
    s += {4: 2.0}.get(len(path), 0)  # 4곳 코스를 기본으로 선호 (5곳은 저장 장소가 많을 때만)
    return round(s, 3)


def _reasons(path: list[Cand], legs: list[int]) -> list[str]:
    saved = sum(1 for c in path if c.source != "external")
    labels = list(dict.fromkeys(c.place.category_label for c in path))
    r = []
    if saved:
        r.append(f"저장한 장소 {saved}곳 포함")
    r.append(" · ".join(labels[:4]))
    if legs:
        r.append(f"장소 사이 최대 도보 {max(legs)}분")
    return r


# ------------------------------------------------------------------ 탐색
def _search_paths(nodes: list[Cand], adj: dict[int, set[int]], legs: dict[tuple[int, int], int],
                  anchor_idx: Optional[int]) -> list[tuple[float, list[int]]]:
    """길이 3~5 경로를 빔 탐색으로. 기준 장소가 있으면 그 노드에서 양쪽으로 늘려 '기준 포함'을 보장."""
    def leg_list(path):
        return [legs[(a, b)] for a, b in zip(path, path[1:])]

    if anchor_idx is not None:
        frontier = [[anchor_idx]]
    else:
        order = sorted(range(len(nodes)), key=lambda i: -_node_score(nodes[i]))
        frontier = [[i] for i in order]
    found: dict[tuple, tuple[float, list[int]]] = {}
    for length in range(2, MAX_STOPS + 1):
        nxt = []
        for path in frontier:
            ends = [(path[-1], False)] + ([(path[0], True)] if anchor_idx is not None and len(path) > 1 else [])
            for end, at_head in ends:
                for nb in adj[end]:
                    if nb in path:
                        continue
                    np_ = [nb] + path if at_head else path + [nb]
                    nxt.append(np_)
        uniq = {}
        for p in nxt:
            key = tuple(p) if tuple(p) <= tuple(reversed(p)) else tuple(reversed(p))
            if key not in uniq:
                uniq[key] = (_path_score([nodes[i] for i in p], leg_list(p)), p)
        ranked = sorted(uniq.values(), key=lambda x: -x[0])[:BEAM]
        frontier = [p for _, p in ranked]
        if length >= MIN_STOPS:
            for sc, p in ranked:
                key = tuple(p) if tuple(p) <= tuple(reversed(p)) else tuple(reversed(p))
                found[key] = (sc, p)
        if not frontier:
            break
    return sorted(found.values(), key=lambda x: -x[0])


def recommend(req: RecommendRequest, user_pool: list[tuple[Place, str]], search: SearchProvider,
              anchor_place: Optional[Place] = None) -> RecommendResult:
    # 0) 기준 확인
    if req.anchor.type == "place":
        if anchor_place is None:
            return _fail("anchor_not_found", 0)
        center = anchor_place.pos
        region = region_of(*center)
    else:
        region = get_region(req.anchor.region_id or "")
        center = (region.lat, region.lng) if region else None
    if region is None:
        return _fail("unsupported_region", 0)

    # 1) 근처 후보 찾기
    try:
        exclude = frozenset([anchor_place.place_id]) if anchor_place else frozenset()
        cands = gather_candidates(center, region, user_pool, search, exclude_ids=exclude)
    except ExternalSearchError:
        return _fail("external_api_failed", 0, region)
    nodes: list[Cand] = []
    anchor_idx = None
    if anchor_place:
        src = next((s for p, s in user_pool if p.place_id == anchor_place.place_id), "mine")
        nodes.append(Cand(place=anchor_place, source="couple" if src == "couple" else "mine"))
        anchor_idx = 0
    nodes += cands

    # 2) 도보 거리 확인 (10분 이내만 연결)
    adj: dict[int, set[int]] = {i: set() for i in range(len(nodes))}
    legs: dict[tuple[int, int], int] = {}
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            m = walk_minutes(nodes[i].place.pos, nodes[j].place.pos)
            if m <= MAX_LEG_MIN:
                adj[i].add(j)
                adj[j].add(i)
                legs[(i, j)] = legs[(j, i)] = m

    def component(start):
        seen, q = {start}, deque([start])
        while q:
            for nb in adj[q.popleft()]:
                if nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        return seen

    reach = len(component(anchor_idx)) if anchor_idx is not None else \
        max((len(component(i)) for i in range(len(nodes))), default=0)
    if reach < MIN_STOPS:
        return _fail("not_enough_candidates", 2, region, len(nodes))

    # 3) 코스 구성
    ranked = _search_paths(nodes, adj, legs, anchor_idx)
    excluded = set(req.exclude_signatures)
    chosen: list[tuple[float, list[int]]] = []
    for max_overlap in (1, 2):  # 먼저 '기준 외 겹침 1곳 이하'로 고르고, 모자라면 2곳까지 허용
        for sc, p in ranked:
            if len(chosen) >= req.max_courses:
                break
            sig = signature_of([nodes[i].place.place_id for i in p])
            if sig in excluded or any(p == q for _, q in chosen):
                continue
            others = set(i for i in p if i != anchor_idx)
            if any(len(others & set(i for i in q if i != anchor_idx)) > max_overlap for _, q in chosen):
                continue
            chosen.append((sc, p))
    if not chosen:
        return _fail("no_result", 3, region, len(nodes))

    courses = []
    for sc, p in chosen:
        lg = [legs[(a, b)] for a, b in zip(p, p[1:])]
        stops = [RecommendedStop(order=k + 1, place=nodes[i].place, source=nodes[i].source,
                                 is_anchor=(i == anchor_idx), external=nodes[i].source == "external",
                                 walk_from_prev_min=lg[k - 1] if k else None) for k, i in enumerate(p)]
        courses.append(RecommendedCourse(
            signature=signature_of([nodes[i].place.place_id for i in p]), stops=stops, total_walk_min=sum(lg),
            saved_count=sum(1 for i in p if nodes[i].source != "external"),
            external_count=sum(1 for i in p if nodes[i].source == "external"), score=sc,
            reasons=_reasons([nodes[i] for i in p], lg)))
    return RecommendResult(status="ok", courses=courses, steps=_steps(3), candidates_count=len(nodes),
                           region={"region_id": region.region_id, "name": region.name})


# ------------------------------------------------------------------ 코스 편집 보조
def replacement_candidates(course_places: list[Place], index: int, user_pool: list[tuple[Place, str]],
                           search: SearchProvider, limit: int = 8) -> list[Cand]:
    """'장소 교체' 시트: 앞뒤 장소와 모두 도보 10분 이내이고 코스에 없는 후보 (저장한 장소 먼저)."""
    target = course_places[index]
    region = region_of(*target.pos)
    if region is None:
        return []
    in_course = {p.place_id for p in course_places}
    neighbors = [course_places[i] for i in (index - 1, index + 1) if 0 <= i < len(course_places)]
    pool = gather_candidates(target.pos, region, user_pool, search, exclude_ids=frozenset(in_course))
    ok = [c for c in pool if all(walk_minutes(n.pos, c.place.pos) <= MAX_LEG_MIN for n in neighbors)]
    ok.sort(key=lambda c: (c.source == "external", sum(walk_minutes(n.pos, c.place.pos) for n in neighbors)))
    return ok[:limit]


def nearby_places(place: Place, user_pool: list[tuple[Place, str]], search: SearchProvider,
                  limit: int = 3) -> list[Cand]:
    """장소 상세 '주변 놀거리': 도보 10분 이내의 놀거리·카페 (저장한 장소 먼저). 외부 검색 실패 시 저장 장소만."""
    region = region_of(*place.pos)
    if region is None:
        return []
    try:
        pool = gather_candidates(place.pos, region, user_pool, search, exclude_ids=frozenset([place.place_id]))
    except ExternalSearchError:
        pool = [Cand(place=p, source="couple" if s == "couple" else "mine") for p, s in user_pool
                if p.place_id != place.place_id]
    ok = [c for c in pool if c.place.category in FUN_CATS and walk_minutes(place.pos, c.place.pos) <= MAX_LEG_MIN]
    ok.sort(key=lambda c: (c.source == "external", walk_minutes(place.pos, c.place.pos)))
    return ok[:limit]


def to_course_draft(rec: RecommendedCourse, owner_id: str, anchor: Anchor, title: Optional[str] = None) -> Course:
    """'이 코스 선택' → 코스 상세 드래프트 (아직 저장 전, 항목 없음)."""
    stops = [CourseStop(place=s.place, is_anchor=s.is_anchor, external=s.external) for s in rec.stops]
    area = rec.stops[0].place.area_label or ""
    return Course(owner_id=owner_id, title=title or f"{area} 데이트 코스".strip(), anchor=anchor, stops=stops)

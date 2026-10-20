"""저장 장소의 카테고리 추론 (TRD: Spring 의 place_records 에는 카테고리 필드가 없음 → 방법 b).

백엔드가 보낸 저장 장소에 categoryCode 가 없으면
  1) 장소 검색(카카오는 좌표 주변, 네이버는 가까운 지원 지역명)으로 같은 가게를 찾아 그 분류를 쓰고
  2) 못 찾으면 이름 글자로 분류 (예: '○○ 카페' → CAFE)
  3) 그래도 모르면 None → 코스의 카테고리 자리에는 못 들어감 (기준 장소로는 쓸 수 있음)
결과는 (이름, 좌표 약 10m 단위) 기준으로 메모리 캐시. 나중에 DB 에 categoryCode 를 저장하면(방법 a) 이 단계는 건너뜀.
"""
from __future__ import annotations

import threading
from typing import Optional

from .. import geo as geo_mod
from .. import taxonomy
from .categories import CODE_TO_PRIMARY
from .domain import Place
from .search import ExternalSearchError
from .walking import distance_m

_cache: dict[tuple, tuple[str, Optional[str]]] = {}
_lock = threading.Lock()
MATCH_RADIUS_M = 200


def _apply(place: Place, primary: str, sub: Optional[str]) -> Place:
    return place.model_copy(update={"category": primary, "sub_category": sub,
                                    "category_label": taxonomy.PRIMARY.get(primary, {"label": "기타"})["label"]})


def with_code(place: Place, code: Optional[str]) -> Place:
    """백엔드가 categoryCode 를 보낸 경우 그대로 반영."""
    if code and code in CODE_TO_PRIMARY:
        return _apply(place, CODE_TO_PRIMARY[code], None)
    return place


def infer_category(place: Place, search) -> Place:
    if place.category_code:
        return place
    key = (place.name.replace(" ", ""), round(place.lat, 4), round(place.lng, 4))
    with _lock:
        hit = _cache.get(key)
    if hit:
        return _apply(place, *hit) if hit[0] != "other" else place

    found: Optional[tuple[str, Optional[str]]] = None
    try:
        cands = search.nearby(place.lat, place.lng, MATCH_RADIUS_M, query=place.name, limit=10)
        if not cands:
            cands = [p for p in search.search(place.name, 5) if distance_m(place.pos, p.pos) <= MATCH_RADIUS_M]
        best = max(cands, key=lambda p: geo_mod.name_similarity(place.name, p.name), default=None)
        if best and geo_mod.name_similarity(place.name, best.name) >= 0.8 and best.category_code:
            found = (best.category, best.sub_category)
    except ExternalSearchError:
        pass
    if not found:
        t = taxonomy.classify_text(place.name)
        found = t if t else ("other", None)
    with _lock:
        _cache[key] = found
    return _apply(place, *found) if found[0] != "other" else place

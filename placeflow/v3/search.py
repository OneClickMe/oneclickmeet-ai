"""장소 검색 제공자 (V3: 네이버 지역검색).

쓰이는 곳
  - 직접 검색 (장소 이름·주소로 찾기)
  - 링크/스크린샷에서 뽑은 이름 → 후보 확인 목록
  - 코스 추천의 '외부 추천' 후보 수집 (지역명 + 업종 검색어 여러 개)

제공자
  NaverLocalSearch  네이버 검색 API '지역' (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET, 무료 키)
                    - 한 번에 최대 5건, 좌표 기반 주변 검색은 없음 → '지역명 + 업종' 검색어를 여러 개 돌려 모은 뒤 거리로 거름
                    - 결과에 고유 ID 가 없어 place_id = 'nv_' + sha1(이름|도로명주소)
  DemoSearch        키 없이 화면을 확인하기 위한 가상 데이터 (지원 지역 6곳 × 16곳, 이름은 모두 가상)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from .. import hours as hours_mod
from .. import taxonomy
from .domain import Place
from .regions import REGIONS


class ExternalSearchError(Exception):
    """외부 검색 API 실패 (키 오류·네트워크·한도 초과). 추천은 'external_api_failed' 로 처리."""


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, display: int = 5) -> list[Place]: ...


def make_place_id(name: str, road_address: str | None, jibun: str | None = None) -> str:
    n = re.sub(r"\s+", "", name)
    a = re.sub(r"\s+", "", road_address or jibun or "")
    key = n + "|" + a
    return "nv_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _area_from(jibun: str | None, road: str | None) -> str | None:
    for src in (jibun, road):
        for tok in (src or "").split():
            if re.search(r"(동|가)$", tok) and not re.search(r"(시|군|구)$", tok) and len(tok) <= 6:
                return re.sub(r"\d+가$", "", tok) or tok
    return None


def _classify(category_text: str | None, name: str) -> tuple[str, str | None, str]:
    cat = taxonomy.classify_text(category_text, name) or ("other", "other")
    label = taxonomy.PRIMARY[cat[0]]["label"]
    return cat[0], cat[1], label


# ---------------------------------------------------------------- 네이버
class NaverLocalSearch:
    """네이버 지역검색.

    endpoint="hub"    (기본) NAVER API HUB — 네이버 클라우드 플랫폼 콘솔에서 발급한 키.
                      2026-07-31 부터 개발자센터 신규 발급이 끝나 새 키는 모두 HUB 키입니다.
    endpoint="legacy" 개발자센터(developers.naver.com) 기존 키. 2027-06-30 까지 사용 가능.
    환경변수: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, (선택) NAVER_SEARCH_ENDPOINT=hub|legacy
    """

    name = "naver_local"
    ENDPOINTS = {
        "hub": ("https://naverapihub.apigw.ntruss.com/search/v1/local", "X-NCP-APIGW-API-KEY-ID",
                "X-NCP-APIGW-API-KEY", "&format=json"),
        "legacy": ("https://openapi.naver.com/v1/search/local.json", "X-Naver-Client-Id", "X-Naver-Client-Secret", ""),
    }

    def __init__(self, client_id: str | None = None, client_secret: str | None = None, timeout: float = 6.0,
                 cache_ttl: int = 6 * 3600, endpoint: str | None = None):
        self.cid = client_id or os.environ.get("NAVER_CLIENT_ID")
        self.secret = client_secret or os.environ.get("NAVER_CLIENT_SECRET")
        if not (self.cid and self.secret):
            raise ValueError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 필요합니다 (.env)")
        self.endpoint = (endpoint or os.environ.get("NAVER_SEARCH_ENDPOINT") or "hub").strip().lower()
        if self.endpoint not in self.ENDPOINTS:
            raise ValueError("NAVER_SEARCH_ENDPOINT 는 hub 또는 legacy 여야 합니다")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, list[Place]]] = {}

    @staticmethod
    def _coord(v) -> float | None:
        if v in (None, ""):
            return None
        f = float(v)
        return f / 1e7 if abs(f) > 1000 else f  # 현재 응답은 WGS84 ×1e7 정수

    def _to_place(self, it: dict) -> Place | None:
        name = re.sub(r"<[^>]+>", "", it.get("title") or "").strip()
        lat, lng = self._coord(it.get("mapy")), self._coord(it.get("mapx"))
        if not name or lat is None or lng is None:
            return None
        road, jibun = it.get("roadAddress") or None, it.get("address") or None
        cat, sub, label = _classify(it.get("category"), name)
        return Place(place_id=make_place_id(name, road, jibun), name=name, category=cat, sub_category=sub,
                     category_label=label, area_label=_area_from(jibun, road), road_address=road,
                     jibun_address=jibun, lat=lat, lng=lng, phone=it.get("telephone") or None,
                     map_url=it.get("link") or None, provider=self.name)

    def search(self, query: str, display: int = 5) -> list[Place]:
        q = query.strip()
        if not q:
            return []
        hit = self._cache.get(q)
        if hit and time.time() - hit[0] < self.cache_ttl:
            return hit[1][:display]
        base, id_header, secret_header, extra = self.ENDPOINTS[self.endpoint]
        url = f"{base}?query={urllib.parse.quote(q)}&display={min(max(display, 1), 5)}&sort=random{extra}"
        req = urllib.request.Request(url, headers={id_header: self.cid, secret_header: self.secret})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:  # HUB: {"error": {...}} / 개발자센터: {"errorCode", "errorMessage"}
                body = json.loads(e.read().decode("utf-8"))
                err = body.get("error") if isinstance(body.get("error"), dict) else body
                detail = " " + str(err.get("message") or err.get("errorMessage") or err.get("errorCode") or "")
            except Exception:
                pass
            hint = " (키·엔드포인트 확인: NAVER_SEARCH_ENDPOINT)" if e.code in (401, 403) else ""
            raise ExternalSearchError(f"네이버 지역검색 HTTP {e.code}{detail.rstrip()}{hint}") from e
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise ExternalSearchError(f"네이버 지역검색 연결 실패: {e}") from e
        places = [p for p in (self._to_place(it) for it in data.get("items", [])) if p]
        self._cache[q] = (time.time(), places)
        return places


# ---------------------------------------------------------------- 데모 (가상 데이터)
_DEMO_TEMPLATES = [
    # (이름 형식, 대분류, 소분류, 동쪽 m, 북쪽 m, 영업시간)
    ("{a} 파스타집", "restaurant", "western", 0, 0, "매일 11:30-21:30 브레이크타임 15:00-17:00"),
    ("{a} 감성 카페", "cafe", "other", 260, 110, "매일 11:00-22:00"),
    ("{a} 보드게임 카페", "activity", "game", -310, 210, "매일 12:00-24:00"),
    ("{a} 숲길 산책", "nature", "park", 150, -290, None),
    ("{a} 소품샵", "shopping", "shop", -130, -210, None),
    ("{a} 이자카야", "bar", "izakaya", 390, -70, "매일 17:00-02:00"),
    ("{a} 디저트 하우스", "cafe", "dessert", -70, 330, "화-일 12:00-21:00 매주 월요일 휴무"),
    ("{a} 국밥", "restaurant", "korean", 520, 260, "매일 07:00-21:00"),
    ("{a} 전시 공간", "culture", "exhibition", -460, -110, "화-일 10:00-19:00 매주 월요일 휴무"),
    ("{a} 와인바", "bar", "wine_bar", 210, 460, "매일 18:00-01:00"),
    ("{a} 반지 공방", "activity", "workshop", -260, -430, None),
    ("{a} 라멘", "restaurant", "japanese", 640, -310, None),
    ("{a} 로스터리", "cafe", "roastery", -610, 160, None),
    ("{a} 포토부스", "activity", "photo", 90, -90, "매일 10:00-24:00"),
    ("{a} 브런치", "restaurant", "brunch", -390, 430, "매일 09:00-16:00"),
    ("{a} 언덕 카페", "cafe", "other", 1600, 1250, None),  # 반경 밖 (거리 필터 확인용)
]
_CAT_WORDS = {
    "맛집": {"restaurant"}, "음식점": {"restaurant"}, "카페": {"cafe"}, "디저트": {"cafe"}, "술집": {"bar"},
    "바": {"bar"}, "공원": {"nature"}, "산책": {"nature"}, "소품샵": {"shopping"}, "쇼핑": {"shopping"},
    "전시": {"culture"}, "놀거리": {"activity", "culture"}, "보드게임": {"activity"}, "공방": {"activity"},
}


def _demo_places() -> list[Place]:
    out = []
    for r in REGIONS:
        short = r.name.replace("역", "").replace("대입구", "대")
        for tmpl, cat, sub, dx, dy, hrs in _DEMO_TEMPLATES:
            name = tmpl.format(a=short)
            lat = r.lat + dy / 111_320
            lng = r.lng + dx / (111_320 * math.cos(math.radians(r.lat)))
            road = f"서울 (데모) {r.area_query}로 {abs(dx) // 10 + abs(dy) // 10}"
            out.append(Place(place_id=make_place_id(name, road), name=name, category=cat, sub_category=sub,
                             category_label=taxonomy.PRIMARY[cat]["label"], area_label=r.area_query,
                             road_address=road, lat=round(lat, 6), lng=round(lng, 6), provider="demo",
                             opening_hours=hours_mod.parse_hours(hrs) if hrs else None))
    return out


class DemoSearch:
    """오프라인 데모 검색. fail=True 면 외부 API 실패를 흉내냅니다."""

    name = "demo"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.name = "demo_fail" if fail else "demo"
        self.places = _demo_places()

    def search(self, query: str, display: int = 5) -> list[Place]:
        if self.fail:
            raise ExternalSearchError("데모: 외부 검색 실패 시뮬레이션")
        toks = [t for t in re.split(r"\s+", query.strip()) if t]
        if not toks:
            return []
        cats: set[str] = set()
        names = []
        for t in toks:
            if t in _CAT_WORDS:
                cats |= _CAT_WORDS[t]
            else:
                names.append(t)
        res = []
        for p in self.places:
            hay = f"{p.name} {p.area_label} {p.road_address}"
            if cats and p.category not in cats:
                continue
            if all(n in hay or n.replace("동", "") in hay for n in names):
                res.append(p)
        return res[:display]


def get_search_provider(name: str = "auto"):
    """auto: 네이버 키가 있으면 네이버, 없으면 데모."""
    name = (name or "auto").lower()
    if name in ("naver", "naver_local") or (name == "auto" and os.environ.get("NAVER_CLIENT_ID")
                                             and os.environ.get("NAVER_CLIENT_SECRET")):
        return NaverLocalSearch()
    if name in ("demo", "auto"):
        return DemoSearch()
    if name == "demo_fail":
        return DemoSearch(fail=True)
    raise ValueError(f"알 수 없는 검색 제공자: {name}")

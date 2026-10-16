"""장소 저장 흐름 (V3): 링크 / 스크린샷 / 직접 검색 → 후보 확인 → 보관함 저장.

  resolve_candidates()  입력을 받아 '이 장소가 맞나요?' 후보 목록을 만든다 (저장하지 않음)
  save_candidate()      사용자가 고른 후보를 개인 보관함에 저장 (+ 공동 보관함 공유 토글)

결과 상태 (ResolveResult.status)
  candidates          후보 1개 이상 → 후보 확인 화면
  no_match            이름은 뽑았지만 검색 결과 없음 → 직접 검색 화면 (suggested_query 미리 채움)
  recognition_failed  스크린샷에서 장소를 못 찾음 → 스크린샷 인식 실패 화면
  link_unreadable     링크에서 내용을 못 읽음(인스타 로그인 벽 등) → 스크린샷 또는 직접 검색 권유
  search_failed       외부 검색 실패 → 직접 검색 재시도 안내 (링크에서 좌표를 얻었으면 그 후보는 보여줌)
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import geo as geo_mod
from .. import taxonomy
from ..models import PlaceRecord
from .domain import Place, SavedPlace
from .search import ExternalSearchError, SearchProvider, make_place_id

MAX_CANDIDATES = 5

_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def split_share_text(raw: str) -> tuple[Optional[str], Optional[str]]:
    """앱 '공유 → 복사' 문구(예: '[네이버 지도]\n삼형제쭈꾸미 대학로점\n서울 종로구 동숭길 68\nhttps://naver.me/x')
    → (첫 번째 링크, 링크를 뺀 나머지 문구). 나머지 문구는 링크를 못 읽을 때 장소 정보로 쓰입니다."""
    m = _URL_RE.search(raw or "")
    if not m:
        return None, None
    rest = (raw[:m.start()] + " " + raw[m.end():]).strip()
    header = re.match(r"^\[([^\]]{1,20})\]\s*", rest)
    rest = rest[header.end():].strip() if header else rest  # '[네이버 지도]' 머리말 제거
    lines = [l.strip() for l in rest.splitlines() if l.strip()]
    if header and lines and len(lines[0]) <= 30 and not lines[0].startswith("📍"):
        lines[0] = "📍 " + lines[0]  # 지도 앱 공유 문구의 첫 줄 = 상호명
    return m.group(0).rstrip(").,"), ("\n".join(lines) or None)


class Candidate(BaseModel):
    place: Place
    match_score: float = Field(..., ge=0, le=1, description="추출한 이름·주소와 얼마나 맞는지")
    already_saved: bool = False
    from_text: Optional[str] = Field(None, description="이 후보를 찾게 한 추출 이름")


class Extracted(BaseModel):
    name: str
    branch: Optional[str] = None
    address_hint: Optional[str] = None
    category: Optional[str] = None


class ResolveResult(BaseModel):
    status: Literal["candidates", "no_match", "recognition_failed", "link_unreadable", "search_failed"]
    candidates: list[Candidate] = Field(default_factory=list)
    suggested_query: Optional[str] = None
    message: Optional[str] = None
    extracted: list[Extracted] = Field(default_factory=list)


def _place_from_record(r: PlaceRecord) -> Optional[Place]:
    """링크(네이버 플레이스 등)에서 좌표까지 얻은 경우, 검색 없이도 후보로 쓸 수 있게 Place 로 변환."""
    if not r.place.location:
        return None
    a = r.place.address
    return Place(place_id=make_place_id(r.place.name, a.road, a.jibun), name=r.place.name, branch=r.place.branch,
                 category=r.classification.primary_category, sub_category=r.classification.sub_category,
                 category_label=r.classification.primary_label, area_label=a.dong, road_address=a.road,
                 jibun_address=a.jibun, lat=r.place.location.lat, lng=r.place.location.lng, phone=r.place.phone,
                 map_url=r.place.map_url, provider="link", opening_hours=r.details.opening_hours)


_ROAD_CORE = re.compile(r"([가-힣0-9]+(?:로|길)\s*\d+(?:-\d+)?)")


def _road_core(addr: Optional[str]) -> Optional[str]:
    m = _ROAD_CORE.search(addr or "")
    return re.sub(r"\s+", "", m.group(1)) if m else None


def _score(rec_name: str, branch: Optional[str], addr_hint: Optional[str], p: Place) -> float:
    cand = geo_mod.GeoCandidate("search", p.place_id, p.name, None, p.road_address, p.jibun_address, p.lat, p.lng)
    return round(min(1.0, geo_mod.score_candidate(rec_name, branch, addr_hint, None, cand)), 3)


def search_candidates(search: SearchProvider, query: str, is_saved=lambda pid: False) -> ResolveResult:
    """직접 검색 화면. 결과를 그대로 후보로."""
    q = (query or "").strip()
    if not q:
        return ResolveResult(status="no_match", message="장소 이름이나 주소를 입력해 주세요.")
    try:
        places = search.search(q, MAX_CANDIDATES)
    except ExternalSearchError as e:
        return ResolveResult(status="search_failed", suggested_query=q, message=f"검색을 불러오지 못했어요. ({e})")
    cands = [Candidate(place=p, match_score=_score(q, None, None, p), already_saved=is_saved(p.place_id), from_text=q)
             for p in places]
    if not cands:
        return ResolveResult(status="no_match", suggested_query=q, message="검색 결과가 없어요. 다른 이름이나 주소로 찾아보세요.")
    return ResolveResult(status="candidates", candidates=cands)


def candidates_from_records(records: list[PlaceRecord], search: SearchProvider, input_kind: str,
                            is_saved=lambda pid: False, pipeline_message: Optional[str] = None) -> ResolveResult:
    """추출 파이프라인 결과(레코드들) → 네이버 지역검색으로 후보 목록."""
    if not records:
        status = "recognition_failed" if input_kind == "screenshot" else "link_unreadable"
        msg = ("장소 이름이나 주소로 직접 찾아보세요. 장소 이름이 잘 보이는 다른 이미지를 선택해도 좋아요."
               if status == "recognition_failed" else
               ((pipeline_message or "링크에서 장소를 찾지 못했어요.") + " "
                + "네이버 지도·인스타 앱의 '공유 → 복사'로 받은 문구 전체를 붙여넣거나, 스크린샷·직접 검색으로 찾아 주세요."))
        return ResolveResult(status=status, message=msg)

    extracted, pool, search_err = [], {}, None
    for r in records[:3]:
        a = r.place.address
        hint = " ".join(x for x in (a.road, a.jibun) if x) or None
        extracted.append(Extracted(name=r.place.name, branch=r.place.branch, address_hint=hint,
                                   category=r.classification.primary_label))
        area = a.dong or a.sigungu or ""
        full = f"{r.place.name} {r.place.branch or ''}".strip()
        name_unsure = any(e.startswith("상호명 인식 불확실") for e in r.content.evidence)  # 캡쳐 상호명이 깨져 임시 이름 사용
        road = _road_core(a.road)
        road_q = []
        if road:  # 주소로도 찾기: '종로구 동숭길 68' (상호명이 깨진 캡쳐도 주소는 대개 정확)
            tail = _ROAD_CORE.search(a.road).group(1)
            road_q = [f"{a.sigungu or ''} {tail}".strip(), f"{tail} {r.place.name}"]
        name_q = [f"{area} {full}", full, r.place.name]
        queries = list(dict.fromkeys(q.strip() for q in ((road_q + name_q) if name_unsure else (name_q + road_q))
                                     if q.strip()))
        for q in queries:
            try:
                for p in search.search(q, MAX_CANDIDATES):
                    s = _score(r.place.name, r.place.branch, hint, p)
                    if road and _road_core(p.road_address) == road:  # 도로명+건물번호 일치 = 같은 건물
                        s = max(s, 0.9 if not name_unsure else 0.85)
                    if s >= 0.45 and (p.place_id not in pool or pool[p.place_id].match_score < s):
                        pool[p.place_id] = Candidate(place=p, match_score=s, already_saved=is_saved(p.place_id),
                                                     from_text=r.place.name)
            except ExternalSearchError as e:
                search_err = str(e)
                break
            if any(c.match_score >= 0.9 for c in pool.values()):
                break
        direct = _place_from_record(r)
        if direct and not any(geo_mod.name_similarity(direct.name, c.place.name) >= 0.9 for c in pool.values()):
            pool[direct.place_id] = Candidate(place=direct, match_score=0.8, already_saved=is_saved(direct.place_id),
                                              from_text=r.place.name)

    cands = sorted(pool.values(), key=lambda c: c.match_score, reverse=True)[:MAX_CANDIDATES]
    first = records[0].place.name
    if any(e.startswith("상호명 인식 불확실") for e in records[0].content.evidence):
        a = records[0].place.address
        first = (a.road or first) if not cands else first
    if cands:
        return ResolveResult(status="candidates", candidates=cands, extracted=extracted, suggested_query=first)
    if search_err:
        return ResolveResult(status="search_failed", extracted=extracted, suggested_query=first,
                             message="장소 검색을 불러오지 못했어요. 잠시 후 직접 검색으로 다시 찾아보세요.")
    return ResolveResult(status="no_match", extracted=extracted, suggested_query=first,
                         message=f"'{first}'(으)로 찾은 장소가 없어요. 직접 검색으로 찾아보세요.")


def save_candidate(repo, owner_id: str, place: Place, origin: str, source_url: Optional[str] = None,
                   share_with_couple: bool = False) -> SavedPlace:
    """후보 확인 → '개인 보관함에 저장'. 같은 장소를 다시 저장하면 기존 항목을 돌려줌(멱등)."""
    if not place.category_label or place.category_label == "기타":
        place.category_label = taxonomy.PRIMARY.get(place.category, {"label": "기타"})["label"]
    return repo.save_place(owner_id, place, origin=origin, source_url=source_url, share_with_couple=share_with_couple)

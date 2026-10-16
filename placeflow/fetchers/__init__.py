"""출처별 콘텐츠 수집. 결과는 모두 FetchedContent 로 통일합니다."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..models import SourceType
from ..router import RoutedInput, route
from . import html_parse
from .http import HttpClient

MAX_TEXT = 6000


@dataclass
class FetchedContent:
    source_type: SourceType
    url: str | None
    final_url: str | None
    status: str                    # ok | blocked | error | skipped
    title: str = ""
    description: str = ""
    text: str = ""
    ids: dict = field(default_factory=dict)
    note: str = ""

    def combined_text(self) -> str:
        parts = [p for p in (self.title, self.description, self.text) if p]
        seen, out = set(), []
        for p in parts:
            if p not in seen:
                out.append(p)
                seen.add(p)
        return "\n".join(out)[:MAX_TEXT]


_IG_CAPTION = re.compile(r'[:：]\s*["“](.+)["”]\s*\.?\s*$', re.S)


def _http_note(status: int) -> str:
    """사용자에게 보여줄 수집 실패 사유."""
    if status == 451:
        return "사이트 정책(robots.txt)상 자동으로 읽을 수 없는 링크예요."
    if status == 0:
        return "링크에 접속하지 못했어요(네트워크 또는 주소 확인)."
    if status in (401, 403):
        return f"사이트가 자동 접속을 막았어요 (HTTP {status})."
    if status == 404:
        return "페이지를 찾을 수 없어요 (HTTP 404)."
    return f"링크를 읽지 못했어요 (HTTP {status})."


def _instagram(r: RoutedInput, client: HttpClient) -> FetchedContent:
    resp = client.get(r.value)
    parsed = html_parse.parse(resp.text) if resp.text else {"meta": {}, "title": ""}
    desc = parsed["meta"].get("og:description", "")
    title = parsed["meta"].get("og:title", "")
    login_wall = "login" in (resp.final_url or "").lower() or (not desc and not title)
    if resp.status != 200 or login_wall:
        return FetchedContent(r.source_type, r.value, resp.final_url, "blocked", ids=r.ids,
                              note="인스타그램이 비로그인 요청을 막았습니다. 캡쳐 또는 캡션 붙여넣기가 필요합니다.")
    m = _IG_CAPTION.search(desc)
    caption = m.group(1) if m else desc
    return FetchedContent(r.source_type, r.value, resp.final_url, "ok", title=title, text=caption, ids=r.ids)


def _naver_blog(r: RoutedInput, client: HttpClient) -> FetchedContent:
    resp = client.get(r.value)
    if resp.status != 200 or not resp.text:
        return FetchedContent(r.source_type, r.value, resp.final_url, "error", note=_http_note(resp.status))
    p = html_parse.parse(resp.text, root_class="se-main-container")
    body = p["root_text"] or p["text"]
    return FetchedContent(r.source_type, r.value, resp.final_url, "ok",
                          title=p["meta"].get("og:title", p["title"]),
                          description=p["meta"].get("og:description", ""), text=body[:MAX_TEXT])


# 지도 SPA 가 돌려주는 공통 제목 — 상호명이 아니므로 버립니다.
GENERIC_TITLES = {"네이버지도", "네이버 지도", "naver map", "naver지도", "네이버 플레이스", "네이버", "naver", "지도"}
_APOLLO = re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\});?\s*(?:window\.|</script>)", re.S)


def _clean_title(t: str) -> str:
    t = re.sub(r"\s*[:\-|]\s*(네이버|NAVER).*$", "", t or "").strip()
    return "" if t.lower().replace(" ", "") in {g.replace(" ", "") for g in GENERIC_TITLES} else t


def _apollo_place(html_text: str, pid: str | None) -> dict | None:
    """플레이스 페이지에 서버 렌더링된 상태(JSON)에서 장소 기본 정보를 찾습니다.

    ⚠️ 네이버 내부 구조라 예고 없이 바뀔 수 있습니다. 못 찾으면 None → OG 태그로 대체.
    """
    m = _APOLLO.search(html_text or "")
    if not m:
        return None
    try:
        state = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    cands = []
    for key, val in state.items():
        if not isinstance(val, dict) or not isinstance(val.get("name"), str):
            continue
        if not (val.get("roadAddress") or val.get("address")):
            continue
        score = (2 if key.startswith("PlaceDetailBase") else 0) + (1 if pid and pid in key else 0)
        cands.append((score, val))
    if not cands:
        return None
    v = max(cands, key=lambda c: c[0])[1]
    menus, hours_bits = [], []

    def walk(node):
        if isinstance(node, dict):
            # 메뉴: name + price 를 가진 객체
            if isinstance(node.get("name"), str) and node.get("price") not in (None, "") and len(menus) < 15:
                digits = re.sub(r"\D", "", str(node.get("price")))
                if digits and 0 < int(digits) < 2_000_000:
                    menus.append({"name": node["name"][:30], "price": int(digits)})
            # 영업시간: day + 시작/끝 시각을 가진 객체
            day = node.get("day") or node.get("dayOfWeek") or node.get("days")
            st = node.get("start") or node.get("startTime") or node.get("openTime")
            en = node.get("end") or node.get("endTime") or node.get("closeTime")
            if isinstance(day, str) and isinstance(st, str) and isinstance(en, str):
                hours_bits.append(f"{day} {st}-{en}")
            for k, val in node.items():
                if isinstance(val, str) and re.search(r"\d{1,2}:\d{2}\s*[-~]\s*\d{1,2}:\d{2}", val) and len(val) < 120 \
                        and re.search(r"[월화수목금토일]|매일|영업|브레이크|라스트", val + k):
                    hours_bits.append(val)
                else:
                    walk(val)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(state)
    coord = v.get("coordinate") if isinstance(v.get("coordinate"), dict) else {}
    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    return {
        "name": v.get("name"), "category": v.get("category"),
        "road_address": v.get("roadAddress"), "jibun_address": v.get("address"),
        "lng": _f(coord.get("x") or v.get("x")), "lat": _f(coord.get("y") or v.get("y")),
        "phone": v.get("phone") or v.get("virtualPhone"),
        "menus": menus,
        "hours_text": " / ".join(dict.fromkeys(hours_bits))[:300] or None,
    }


def _naver_place(r: RoutedInput, client: HttpClient) -> FetchedContent:
    """네이버 지도/플레이스 링크.

    지도 링크(map.naver.com)는 JS로 그려져 HTML 에 정보가 없으므로, place ID 로 플레이스 페이지를 직접 시도합니다.
    순서: ① 플레이스 페이지의 내장 JSON → ② OG 메타태그 → ③ 실패 시 사용자에게 상호명/캡쳐 요청
    """
    pid = r.ids.get("naver_place_id")
    urls = []
    if pid:
        urls += [f"https://pcmap.place.naver.com/place/{pid}/home", f"https://m.place.naver.com/place/{pid}/home"]
    urls.append(r.value)
    last_status, final_url, tried = 0, r.value, []
    for u in dict.fromkeys(urls):
        resp = client.get(u)
        last_status, final_url = resp.status, resp.final_url
        tried.append(f"{u.split('/')[2]}:{'robots.txt 금지' if resp.status == 451 else resp.status}")
        if resp.status != 200 or not resp.text:
            continue
        info = _apollo_place(resp.text, pid)
        p = html_parse.parse(resp.text)
        og_title = _clean_title(p["meta"].get("og:title") or p["title"])
        desc = p["meta"].get("og:description", "")
        if info and info.get("name"):
            lines = [f"📍{info['name']}"]
            if info.get("road_address") or info.get("jibun_address"):
                lines.append(f"주소: {info.get('road_address') or info.get('jibun_address')}")
            if info.get("category"):
                lines.append(f"카테고리: {info['category']}")
            if info.get("phone"):
                lines.append(f"전화: {info['phone']}")
            if info.get("hours_text"):
                lines.append(f"영업시간: {info['hours_text']}")
            for m in info.get("menus", [])[:10]:
                lines.append(f"{m['name']} {m['price']:,}원")
            ids = {**r.ids, "naver_place_info": info}
            return FetchedContent(r.source_type, r.value, resp.final_url, "ok", title=info["name"],
                                  description=desc, text="\n".join(lines), ids=ids, note="naver_place:embedded_json")
        if og_title:
            return FetchedContent(r.source_type, r.value, resp.final_url, "ok", title=og_title,
                                  description=desc, ids=r.ids, note="naver_place:og_meta")
    return FetchedContent(
        r.source_type, r.value, final_url, "blocked" if last_status in (0, 403, 429) else "error", ids=r.ids,
        note=("네이버 지도 페이지에서 상호명을 읽지 못했습니다(지도는 자바스크립트로 그려지는 페이지). "
              "상호명을 메모에 적거나 플레이스 화면 캡쳐를 올려 주세요. [시도: " + ", ".join(tried) + "]"))


def _generic(r: RoutedInput, client: HttpClient) -> FetchedContent:
    resp = client.get(r.value)
    if resp.status != 200 or not resp.text:
        return FetchedContent(r.source_type, r.value, resp.final_url, "error", note=_http_note(resp.status))
    p = html_parse.parse(resp.text)
    return FetchedContent(r.source_type, r.value, resp.final_url, "ok",
                          title=p["meta"].get("og:title", p["title"]),
                          description=p["meta"].get("og:description", ""), text=p["text"][:MAX_TEXT])


def fetch_link(r: RoutedInput, client: HttpClient, _depth: int = 0) -> FetchedContent:
    if r.source_type == SourceType.naver_short:
        resp = client.get(r.value)
        if _depth < 2 and resp.final_url and resp.final_url != r.value:
            again = route(resp.final_url, r.extra_text)
            if again.source_type != SourceType.naver_short:
                fc = fetch_link(again, client, _depth + 1)
                fc.url = r.value
                return fc
        return FetchedContent(r.source_type, r.value, resp.final_url, "error", note="단축 링크를 풀지 못했습니다.")
    handler = {
        SourceType.instagram_link: _instagram,
        SourceType.naver_blog: _naver_blog,
        SourceType.naver_place: _naver_place,
    }.get(r.source_type, _generic)
    return handler(r, client)

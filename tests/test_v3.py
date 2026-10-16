"""V3 (Figma V3 기준) 장소 저장 · 도보 코스 추천 · 코스 편집 테스트. 네트워크 없이 DemoSearch 로 실행."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from placeflow.v3 import api as v3api
from placeflow.v3.domain import (Anchor, Course, CourseStop, DomainError, add_item, add_stop, remove_stop,
                                 reorder_stops, replace_stop, summarize, update_item, validate_for_save)
from placeflow.v3.recommend import RecommendRequest, recommend, replacement_candidates, signature_of
from placeflow.v3.regions import get_region, region_of
from placeflow.v3.repo import JsonRepo
from placeflow.v3.save_flow import candidates_from_records, search_candidates
from placeflow.v3.search import DemoSearch, make_place_id
from placeflow.v3.service import OneClickMeetService
from placeflow.v3.walking import ANCHOR_RADIUS_M, MAX_LEG_MIN, distance_m, walk_minutes


@pytest.fixture
def demo():
    return DemoSearch()


@pytest.fixture
def svc(tmp_path, demo):
    return OneClickMeetService(JsonRepo(tmp_path / "db.json"), demo, None)


def _places(demo, area="연남", n=5):
    return [p for p in demo.places if p.name.startswith(area + " ")][:n]


def _course(demo, n=4):
    return Course(owner_id="me", stops=[CourseStop(place=p) for p in _places(demo, n=n)])


# ------------------------------------------------------------------ 도보 · 지역
def test_walk_minutes_rule():
    a, b = (37.5626, 126.9255), (37.5626, 126.9255 + 0.0113)  # 약 1km 동쪽
    assert 990 < distance_m(a, b) < 1010
    assert walk_minutes(a, b) == 18  # 1km × 1.3 ÷ 4.5km/h = 17.3 → 올림
    assert walk_minutes(a, a) == 1


def test_region_lookup():
    r = get_region("yeonnam")
    assert region_of(r.lat, r.lng).region_id == "yeonnam"
    assert region_of(35.1, 129.0) is None  # 부산 → 미지원


def test_place_id_stable_and_space_insensitive():
    assert make_place_id("연남 카페", "서울 마포구 1") == make_place_id("연남카페", "서울  마포구 1")
    assert make_place_id("A", "x").startswith("nv_")


# ------------------------------------------------------------------ 코스 항목 규칙
def test_items_follow_reorder_but_not_replace_or_delete(demo):
    c = _course(demo)
    s0, s1 = c.stops[0].stop_id, c.stops[1].stop_id
    c = add_item(c, s0, "파스타 2개", 30000)
    c = add_item(c, s1, "커피", 12000, checked=False)
    c2 = reorder_stops(c, [s.stop_id for s in reversed(c.stops)])
    assert len(c2.items) == 2 and c2.stops[-1].stop_id == s0
    c3 = replace_stop(c2, s0, _places(demo, n=6)[5])
    assert [i.stop_id for i in c3.items] == [s1]
    c4 = remove_stop(c3, s1)
    assert c4.items == []


def test_summary_confirmed_total_and_unchecked(demo):
    c = _course(demo)
    s = [x.stop_id for x in c.stops]
    c = add_item(c, s[0], "a", 10000)
    c = add_item(c, s[0], "b", 5000, checked=False)
    c = add_item(c, s[1], "c", 7000, checked=False)
    sm = summarize(c)
    assert sm.confirmed_total == 10000
    assert sm.unchecked_stop_count == 3  # s1(체크 없음) + 항목 없는 2곳
    c = update_item(c, c.items[2].item_id, checked=True)
    assert summarize(c).confirmed_total == 17000


def test_validate_3_to_5_and_duplicates(demo):
    assert "too_few_stops" in validate_for_save(_course(demo, 2))
    assert validate_for_save(_course(demo, 5)) == []
    c = _course(demo, 5)
    with pytest.raises(DomainError) as e:
        add_stop(c, _places(demo, n=6)[5])
    assert e.value.code == "too_many_stops"
    with pytest.raises(DomainError) as e:
        add_stop(_course(demo, 3), c.stops[0].place)
    assert e.value.code == "duplicate_place"


def test_reorder_requires_same_set(demo):
    c = _course(demo)
    with pytest.raises(DomainError):
        reorder_stops(c, [c.stops[0].stop_id])


def test_item_amount_bounds(demo):
    c = _course(demo)
    with pytest.raises(Exception):
        add_item(c, c.stops[0].stop_id, "x", -1)


# ------------------------------------------------------------------ 저장소
def test_repo_version_conflict_and_memo_privacy(tmp_path, demo):
    repo = JsonRepo(tmp_path / "r.json")
    c = repo.save_course(_course(demo))
    assert c.version == 1
    repo.save_course(c, expected_version=1)
    with pytest.raises(DomainError) as e:
        repo.save_course(c, expected_version=1)
    assert e.value.code == "version_conflict"
    repo.set_memo("me", "place", "p1", "비밀")
    assert repo.get_memo("me", "place", "p1").text == "비밀"
    assert repo.get_memo("you", "place", "p1") is None
    repo.set_memo("me", "place", "p1", "")
    assert repo.get_memo("me", "place", "p1") is None


def test_saving_course_does_not_fill_box(svc, demo):
    svc.save_course("me", _course(demo).model_dump(mode="json"))
    assert svc.list_saved("me")["count"] == 0


def test_save_place_idempotent(svc, demo):
    p = demo.places[0].model_dump(mode="json")
    svc.save_place("me", p)
    svc.save_place("me", p)
    assert svc.list_saved("me")["count"] == 1
    assert svc.unsave_place("me", demo.places[0].place_id)["removed"]


# ------------------------------------------------------------------ 추천
def _pool(demo, names):
    return [(p, "mine") for p in demo.places if p.name in names]


def _check_course(c, center, anchor_id=None):
    ids = [s.place.place_id for s in c.stops]
    assert 3 <= len(c.stops) <= 5
    assert len(set(ids)) == len(ids)
    for s in c.stops:
        assert distance_m(center, s.place.pos) <= ANCHOR_RADIUS_M + 1
    for a, b in zip(c.stops, c.stops[1:]):
        assert walk_minutes(a.place.pos, b.place.pos) <= MAX_LEG_MIN
    if anchor_id:
        assert sum(s.is_anchor for s in c.stops) == 1 and anchor_id in ids


def test_recommend_place_anchor(demo):
    pool = _pool(demo, {"연남 파스타집", "연남 감성 카페", "연남 와인바"})
    anchor = next(p for p, _ in pool if p.name == "연남 파스타집")
    res = recommend(RecommendRequest(anchor=Anchor(type="place", place_id=anchor.place_id)), pool, demo, anchor)
    assert res.status == "ok" and len(res.courses) == 3
    assert len({c.signature for c in res.courses}) == 3
    for c in res.courses:
        _check_course(c, anchor.pos, anchor.place_id)
    assert all(s.done for s in res.steps)
    # 다시 추천: 이전 코스 제외
    again = recommend(RecommendRequest(anchor=Anchor(type="place", place_id=anchor.place_id),
                                       exclude_signatures=[c.signature for c in res.courses]), pool, demo, anchor)
    assert again.status in ("ok", "no_result")
    assert not {c.signature for c in again.courses} & {c.signature for c in res.courses}


def test_recommend_region_anchor(demo):
    r = get_region("jamsil")
    res = recommend(RecommendRequest(anchor=Anchor(type="region", region_id="jamsil")), [], demo)
    assert res.status == "ok"
    for c in res.courses:
        _check_course(c, (r.lat, r.lng))
        assert all(s.source == "external" for s in c.stops)


def test_recommend_failures(demo):
    far = demo.places[0].model_copy(update={"lat": 35.1, "lng": 129.0, "place_id": "far"})
    res = recommend(RecommendRequest(anchor=Anchor(type="place", place_id="far")), [(far, "mine")], demo, far)
    assert res.status == "unsupported_region"
    res = recommend(RecommendRequest(anchor=Anchor(type="region", region_id="seochon")), [], DemoSearch(fail=True))
    assert res.status == "external_api_failed"
    res = recommend(RecommendRequest(anchor=Anchor(type="place", place_id="nope")), [], demo, None)
    assert res.status == "anchor_not_found"


def test_signature_order_independent():
    assert signature_of(["b", "a"]) == signature_of(["a", "b"])


def test_replacement_candidates_walkable(demo):
    ps = _places(demo, n=4)
    cands = replacement_candidates(ps, 1, [(ps[2], "mine")], demo)
    for c in cands:
        assert c.place.place_id not in {p.place_id for p in ps}
        assert walk_minutes(ps[0].pos, c.place.pos) <= MAX_LEG_MIN
        assert walk_minutes(c.place.pos, ps[2].pos) <= MAX_LEG_MIN


# ------------------------------------------------------------------ 저장 흐름
def test_search_candidates_statuses(demo):
    assert search_candidates(demo, "연남 카페").status == "candidates"
    assert search_candidates(demo, "없는장소이름").status == "no_match"
    assert search_candidates(DemoSearch(fail=True), "연남 카페").status == "search_failed"


def test_candidates_from_empty_records(demo):
    assert candidates_from_records([], demo, "screenshot").status == "recognition_failed"
    assert candidates_from_records([], demo, "link").status == "link_unreadable"


# ------------------------------------------------------------------ 서비스 · HTTP
def test_service_flow(svc):
    svc.seed_demo("me", "yeonnam")
    pid = svc.list_saved("me")["items"][0]["place"]["place_id"]
    rec = svc.recommend("me", {"type": "place", "place_id": pid})
    assert rec["status"] == "ok"
    d = svc.draft_from_recommendation("me", rec["courses"][0], {"type": "place", "place_id": pid})
    c = svc.apply_op("me", d["course"], {"type": "add_item", "stop_id": d["course"]["stops"][0]["stop_id"],
                                         "name": "점심", "amount": 20000})
    assert c["summary"]["confirmed_total"] == 20000
    saved = svc.save_course("me", c["course"], memo="m")
    assert saved["course"]["version"] == 1 and saved["my_memo"] == "m"
    with pytest.raises(DomainError):
        svc.save_course("me", saved["course"], expected_version=0)
    with pytest.raises(DomainError):
        svc.get_course("intruder", saved["course"]["course_id"])


@pytest.fixture
def http_server(tmp_path):
    from http.server import ThreadingHTTPServer

    from placeflow.server import Handler

    v3api.use_repo(JsonRepo(tmp_path / "h.json"), "demo")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/api/v3"
    httpd.shutdown()
    httpd.server_close()


def _call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_endpoints(http_server):
    b = http_server
    assert _call(b, "POST", "/dev/seed", {"region_id": "hyehwa"})[0] == 200
    s, r = _call(b, "GET", "/regions")
    assert next(x for x in r["data"]["regions"] if x["region_id"] == "hyehwa")["saved_count"] == 4
    s, r = _call(b, "GET", "/places/search?q=" + urllib.request.quote("혜화 카페"))
    assert r["ok"] and r["data"]["status"] == "candidates" and r["data"]["candidates"][0]["place"]["subtitle"]
    s, r = _call(b, "GET", "/saved-places")
    pid = r["data"]["items"][0]["place"]["place_id"]
    s, r = _call(b, "GET", "/places/" + pid)
    assert r["data"]["hearted"] and "hours_notice" in r["data"]["place"]
    anchor = {"type": "place", "place_id": pid}
    rec = _call(b, "POST", "/recommendations", {"anchor": anchor})[1]["data"]
    assert rec["status"] == "ok"
    d = _call(b, "POST", "/courses/draft", {"recommended": rec["courses"][0], "anchor": anchor})[1]["data"]
    s, r = _call(b, "POST", "/courses", {"course": d["course"]})
    cid, course = r["data"]["course"]["course_id"], r["data"]["course"]
    assert _call(b, "PUT", "/courses/" + cid, {"course": course, "expected_version": 1})[0] == 200
    s, r = _call(b, "PUT", "/courses/" + cid, {"course": course, "expected_version": 1})
    assert s == 409 and r["error"]["code"] == "version_conflict"
    few = dict(course, stops=course["stops"][:2], items=[])
    s, r = _call(b, "PUT", "/courses/" + cid, {"course": few, "expected_version": 2})
    assert s == 422 and r["error"]["code"] == "too_few_stops"
    assert _call(b, "GET", "/nope")[0] == 404
    assert _call(b, "POST", "/recommendations", {})[1]["error"]["code"] == "invalid_input"
    assert _call(b, "DELETE", "/courses/" + cid)[1]["data"]["deleted"]


# ------------------------------------------------------------------ OCR 보강 (상호명이 깨진 플레이스 캡쳐)
def test_ocr_merge_fixes_garbled_name_and_address():
    from placeflow.ocr import merge_variants, ocr_quality

    bad = "place+\nAPSARA] 대학로점\n주꾸미요리 ㆍ ※4.42 ㆍ리뷰 2,952\n영업 중\n서울 종로구 SSE 68\n02-763-1204"
    good = "place+\n삼형제쭈꾸미 대학로점\n주꾸미요리 ㆍ 4.42 ㆍ 리뷰 2,952\n영업 중\n서울 종로구 동숭길 68\n"
    assert ocr_quality(good) > ocr_quality(bad)
    merged = merge_variants([bad, "주 꾸 미 요 리 ㆍ 리 뷰\nSAFO 대학로점\n서울 종로구 동숭길 68"])
    assert "APSARA" not in merged.splitlines()[1] or "동숭길 68" in merged
    assert "동숭길 68" in merged


def test_garbled_place_capture_resolves_by_address():
    from placeflow.pipeline import Pipeline
    from placeflow.v3.domain import Place

    text = "place+\nSal 770| 대학로점\n주꾸미요리 ㆍ 4.42 ㆍ 리뷰 2,952\n영업 중 ㆍ 22:00에 영업 종료\n서울 종로구 동숭길 68\n02-763-1204 복사"
    out = Pipeline().run(text)
    assert out.records and out.records[0].place.address.road == "서울 종로구 동숭길 68"

    target = Place(place_id="nv_x", name="삼형제쭈꾸미 대학로점", category="restaurant", category_label="맛집",
                   road_address="서울특별시 종로구 동숭길 68", lat=37.5826, lng=127.0023, provider="naver_local")
    other = Place(place_id="nv_y", name="동숭길 카페", category="cafe", road_address="서울특별시 종로구 동숭길 12",
                  lat=37.58, lng=127.0, provider="naver_local")

    class Fake:
        name = "fake"
        def search(self, q, display=5):
            return [target, other] if "동숭길" in q else []

    res = candidates_from_records(out.records, Fake(), "screenshot")
    assert res.status == "candidates" and res.candidates[0].place.place_id == "nv_x"
    assert all(c.place.place_id != "nv_y" for c in res.candidates)


def test_share_text_used_when_link_blocked_by_robots():
    from placeflow.fetchers.http import ROBOTS_BLOCKED, HttpResponse
    from placeflow.pipeline import Pipeline
    from placeflow.v3.api import split_share_text

    url, rest = split_share_text("[네이버 지도]\n삼형제쭈꾸미 대학로점\n서울 종로구 동숭길 68\nhttps://naver.me/5abcDEF")
    assert url == "https://naver.me/5abcDEF" and "삼형제쭈꾸미 대학로점" in rest
    assert split_share_text("링크 없음") == (None, None)

    class Blocked:
        def get(self, u):
            return HttpResponse(u, u, ROBOTS_BLOCKED, "")

    pipe = Pipeline(http=Blocked())
    out = pipe.run("https://map.naver.com/p/entry/place/1234567")
    assert not out.records and "robots.txt" in (out.message or "")
    res = candidates_from_records(out.records, DemoSearch(), "link", pipeline_message=out.message)
    assert res.status == "link_unreadable" and "공유" in res.message
    out2 = pipe.run(url, rest)
    assert out2.records and out2.records[0].place.name.startswith("삼형제쭈꾸미")
    assert out2.records[0].place.address.road == "서울 종로구 동숭길 68"


# ------------------------------------------------------------------ 링크 하나에 장소 여러 곳 (인스타 '맛집 4곳' 릴스)
def _jamsil_db():
    from placeflow.v3.domain import Place

    def P(i, name, road, cat="restaurant"):
        return Place(place_id=i, name=name, road_address=road, category=cat, lat=37.51, lng=127.11,
                     provider="naver_local")
    return [P("a", "오지다", "서울특별시 송파구 백제고분로48길 24"),
            P("b", "회포차오지다", "서울특별시 송파구 가락로 241 1층"),
            P("c", "닭튜브 방이점", "서울특별시 송파구 백제고분로48길 7 1층"),
            P("d", "일일식탁", "서울특별시 송파구 올림픽로35길 124 장미종합A상가 A-2동 지하1층"),
            P("e", "일일식탁 강남점", "서울특별시 강남구 테헤란로 1"),
            P("f", "리사르커피", "서울특별시 송파구 올림픽로35길 112 B동", "cafe")]


class _FakeNaver:
    name = "fake"

    def __init__(self, db):
        self.db, self.calls = db, []

    def search(self, q, display=5):
        self.calls.append(q)
        toks = [x for x in q.split() if not x.endswith(("구", "동"))]
        return [p for p in self.db if any(x.replace(" ", "") in (p.name + p.road_address).replace(" ", "")
                                           for x in toks)][:display]


def test_multi_place_caption_groups():
    from pathlib import Path

    from placeflow.pipeline import Pipeline

    caption = (Path(__file__).parent / "fixtures" / "ig_jamsil_4places.txt").read_text(encoding="utf-8")
    recs = Pipeline().run(caption).records
    assert [r.place.name for r in recs] == ["오지다", "닭튜브", "일일식탁", "리사르커피"]
    cats = {r.place.name: (r.classification.primary_category, r.classification.sub_category) for r in recs}
    assert cats["닭튜브"] == ("restaurant", "chicken") and cats["일일식탁"] == ("restaurant", "korean")

    res = candidates_from_records(recs, _FakeNaver(_jamsil_db()), "link")
    assert res.status == "candidates"
    assert [g.extracted.name for g in res.groups] == ["오지다", "닭튜브", "일일식탁", "리사르커피"]  # 4번째도 검색됨
    assert [g.extracted.order for g in res.groups] == [1, 2, 3, 4]
    best = {g.extracted.name: g.best.place.place_id for g in res.groups}
    assert best == {"오지다": "a", "닭튜브": "c", "일일식탁": "d", "리사르커피": "f"}
    g0 = res.groups[0]
    assert "주소 일치" in g0.best.reasons
    hoe = next(c for c in g0.others if c.place.place_id == "b")  # 회포차오지다: 기본 선택 안 함
    assert hoe.match_type == "similar" and "이름 일부만 같아요" in hoe.reasons and "주소 다름" in hoe.reasons
    gangnam = next(c for c in res.groups[2].others if c.place.place_id == "e")
    assert gangnam.match_type == "similar"
    assert all(c.match_type == "similar" for g in res.groups for c in g.others)


def test_match_rules():
    from placeflow.v3.save_flow import match

    db = {p.place_id: p for p in _jamsil_db()}
    assert match("닭튜브", None, None, [], db["c"])[0] == "exact"            # '○○점' 지점명 허용
    assert match("오지다", None, None, [], db["b"])[0] == "similar"          # 이름 일부만
    assert match("오지다", None, "백제고분로48길24", [], db["b"])[2][-1] == "주소 다름"
    assert match("오지다", None, None, [], db["c"]) is None                  # 무관한 가게
    assert match("일일식탁", None, None, [("장미", "상가")], db["d"])[2] == ["이름 일치", "장미상가 일치"]


def test_similar_only_group_has_no_best():
    from placeflow.pipeline import Pipeline

    recs = Pipeline().run("📍오지다 서울 송파구 가락로 999").records
    res = candidates_from_records(recs, _FakeNaver(_jamsil_db()), "link")
    g = res.groups[0]
    assert g.best is None and g.status == "similar_only" and g.others


def test_batch_save(svc, demo):
    ps = [p.model_dump(mode="json") for p in demo.places[:3]]
    out = svc.save_places("me", ps, origin="link", source_url="https://instagram.com/reel/x")
    assert out["count"] == 3 and svc.list_saved("me")["count"] == 3
    with pytest.raises(DomainError):
        svc.save_places("me", [])


def test_embedded_cuisine_word_ignored():
    from placeflow import taxonomy

    assert taxonomy.classify_text("일일식탁") is None
    assert taxonomy.classify_text("일식당 하루") == ("restaurant", "japanese")

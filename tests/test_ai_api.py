"""AI 서버(FastAPI) 계약 테스트. 네트워크 없이: 네이버는 가짜 검색, 링크 수집은 차단 클라이언트."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from placeflow.ai_api import deps  # noqa: E402
from placeflow.fetchers.http import HttpResponse  # noqa: E402
from placeflow.pipeline import Pipeline  # noqa: E402
from placeflow.v3.domain import Place  # noqa: E402
from placeflow.v3.search import DemoSearch, ExternalSearchError  # noqa: E402

CAPTION = (Path(__file__).parent / "fixtures" / "ig_jamsil_4places.txt").read_text(encoding="utf-8")


def P(i, name, road, cat="restaurant", lat=37.5131, lng=127.1123):
    return Place(place_id=i, name=name, road_address=road, category=cat, lat=lat, lng=lng, provider="naver_local")


JAMSIL = [P("a", "오지다", "서울특별시 송파구 백제고분로48길 24"),
          P("b", "회포차오지다", "서울특별시 송파구 가락로 241 1층"),
          P("c", "닭튜브 방이점", "서울특별시 송파구 백제고분로48길 7 1층"),
          P("d", "일일식탁", "서울특별시 송파구 올림픽로35길 124 장미종합A상가 A-2동 지하1층"),
          P("f", "리사르커피", "서울특별시 송파구 올림픽로35길 112 B동", "cafe")]


class FakeNaver:
    name = "fake"

    def search(self, q, display=5):
        toks = [x for x in q.split() if not x.endswith(("구", "동"))]
        return [p for p in JAMSIL if any(x.replace(" ", "") in (p.name + p.road_address).replace(" ", "")
                                          for x in toks)][:display]


class Blocked:
    def get(self, u):
        return HttpResponse(u, u, 0, "")


@pytest.fixture
def make_client(monkeypatch):
    def _make(search=None, api_key=None):
        from placeflow.ai_api.main import create_app

        monkeypatch.setattr(deps, "_pipe", Pipeline(http=Blocked()))
        deps.get_settings.cache_clear()
        if api_key:
            monkeypatch.setenv("AI_SERVICE_KEY", api_key)
        else:
            monkeypatch.delenv("AI_SERVICE_KEY", raising=False)
        app = create_app()
        app.dependency_overrides[deps.get_search] = lambda: (search or FakeNaver())
        return TestClient(app)
    yield _make
    deps.get_settings.cache_clear()


def test_health_and_regions(make_client):
    c = make_client()
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["workflow_version"] == "1.1" and h["auth_required"] is False
    r = c.get("/ai/v1/regions").json()
    assert r["ok"] and len(r["data"]["regions"]) == 6 and r["data"]["regions"][0]["radius_m"] > 0
    assert "/ai/v1/recommendations" in c.get("/openapi.json").json()["paths"]


def test_resolve_link_with_caption_groups(make_client):
    c = make_client()
    r = c.post("/ai/v1/places/resolve", json={"type": "link", "url": "https://www.instagram.com/reel/DegiE1ozc74/",
                                               "note": CAPTION, "saved_place_ids": ["c"]})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "candidates"
    assert [g["extracted"]["name"] for g in d["groups"]] == ["오지다", "닭튜브", "일일식탁", "리사르커피"]
    g0 = d["groups"][0]
    assert g0["best"]["place"]["place_id"] == "a" and g0["best"]["place"]["subtitle"]
    assert all(o["match_type"] == "similar" for o in g0["others"])
    assert d["groups"][1]["best"]["already_saved"] is True


def test_resolve_share_text_and_errors(make_client):
    c = make_client()
    share = "[네이버 지도]\n오지다\n서울 송파구 백제고분로48길 24\nhttps://naver.me/abc"
    d = c.post("/ai/v1/places/resolve", json={"type": "link", "url": share}).json()["data"]
    assert d["groups"][0]["best"]["place"]["place_id"] == "a"
    r = c.post("/ai/v1/places/resolve", json={"type": "link", "url": "링크 없음"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_input"
    r = c.post("/ai/v1/places/resolve", json={"type": "nope"})
    assert r.status_code == 400 and r.json()["ok"] is False
    d = c.post("/ai/v1/places/resolve", json={"type": "link", "url": "https://map.naver.com/p/entry/place/1"}).json()
    assert d["data"]["status"] == "link_unreadable"


def test_screenshot_upload_limits(make_client):
    c = make_client()
    r = c.post("/ai/v1/places/resolve/screenshot", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert r.status_code == 400 and "형식" in r.json()["error"]["message"]
    six = [("files", (f"{i}.png", b"x", "image/png")) for i in range(6)]
    assert c.post("/ai/v1/places/resolve/screenshot", files=six).status_code == 400
    r = c.post("/ai/v1/places/resolve/screenshot", files=[("files", ("a.png", b"", "image/png"))])
    assert r.status_code == 400


def test_screenshot_ocr_path(make_client, monkeypatch):
    """OCR 결과를 흉내 내 스크린샷 경로 전체(업로드 → 인식 → 주소 매칭 → 임시파일 삭제)를 확인."""
    seen = []

    class FakeOCR:
        name = "fake"

        def read(self, path):
            seen.append(path)
            return "place+\nSal 770| 대학로점\n주꾸미요리 ㆍ 4.42 ㆍ 리뷰 2,952\n영업 중\n서울 송파구 백제고분로48길 24\n"

    c = make_client()
    monkeypatch.setattr(deps, "_pipe", Pipeline(http=Blocked(), ocr=FakeOCR()))
    r = c.post("/ai/v1/places/resolve/screenshot", files=[("files", ("cap.png", io.BytesIO(b"\x89PNG fake"), "image/png"))],
               data={"saved_place_ids": ["a"]})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["groups"][0]["best"]["place"]["place_id"] == "a" and d["groups"][0]["best"]["already_saved"]
    assert seen and not Path(seen[0]).exists()  # 임시 파일 정리


def test_search(make_client):
    c = make_client()
    d = c.get("/ai/v1/places/search", params={"q": "리사르커피"}).json()["data"]
    assert d["status"] == "candidates" and d["candidates"][0]["place"]["name"] == "리사르커피" and d["groups"] == []
    c2 = make_client(search=DemoSearch(fail=True))
    assert c2.get("/ai/v1/places/search", params={"q": "x"}).json()["data"]["status"] == "search_failed"


def _saved(names, demo):
    return [{"place": p.model_dump(mode="json"), "source": "mine"} for p in demo.places if p.name in names]


def test_recommendations_stateless(make_client):
    demo = DemoSearch()
    c = make_client(search=demo)
    saved = _saved({"연남 파스타집", "연남 감성 카페", "연남 와인바"}, demo)
    anchor_id = next(s["place"]["place_id"] for s in saved if s["place"]["name"] == "연남 파스타집")
    body = {"anchor": {"type": "place", "place_id": anchor_id}, "saved_places": saved}
    d = c.post("/ai/v1/recommendations", json=body).json()["data"]
    assert d["status"] == "ok" and len(d["courses"]) == 3
    assert all(any(s["is_anchor"] and s["place"]["place_id"] == anchor_id for s in co["stops"]) for co in d["courses"])
    sigs = [co["signature"] for co in d["courses"]]
    again = c.post("/ai/v1/recommendations", json={**body, "exclude_signatures": sigs}).json()["data"]
    assert not {co["signature"] for co in again["courses"]} & set(sigs)
    # 기준 장소 정보를 안 보내면(보관함에도 없음) anchor_not_found
    d = c.post("/ai/v1/recommendations", json={"anchor": {"type": "place", "place_id": "zzz"}}).json()["data"]
    assert d["status"] == "anchor_not_found"
    d = c.post("/ai/v1/recommendations", json={"anchor": {"type": "region", "region_id": "jamsil"}}).json()["data"]
    assert d["status"] == "ok"
    fail = make_client(search=DemoSearch(fail=True))
    d = fail.post("/ai/v1/recommendations", json={"anchor": {"type": "region", "region_id": "jamsil"}}).json()["data"]
    assert d["status"] == "external_api_failed"


def test_replacements_and_nearby(make_client):
    demo = DemoSearch()
    c = make_client(search=demo)
    ps = [p for p in demo.places if p.name.startswith("연남 ")][:4]
    body = {"course_places": [p.model_dump(mode="json") for p in ps], "index": 1}
    d = c.post("/ai/v1/recommendations/replacements", json=body).json()
    assert d["ok"] and all(x["place"]["place_id"] not in {p.place_id for p in ps} for x in d["data"]["candidates"])
    r = c.post("/ai/v1/recommendations/replacements", json={**body, "index": 9})
    assert r.status_code == 400
    d = c.post("/ai/v1/places/nearby", json={"place": ps[0].model_dump(mode="json")}).json()
    assert d["ok"] and len(d["data"]["candidates"]) <= 3


def test_api_key(make_client):
    c = make_client(api_key="secret")
    r = c.get("/ai/v1/regions")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert c.get("/ai/v1/regions", headers={"X-AI-Key": "secret"}).status_code == 200
    assert c.get("/health").status_code == 200  # 상태 확인은 키 없이


def test_external_error_envelope(make_client):
    class Boom:
        name = "boom"

        def search(self, q, display=5):
            raise ExternalSearchError("down")

    c = make_client(search=Boom())
    # 주변 놀거리는 외부 실패 시 저장 장소만 → 200
    p = DemoSearch().places[0].model_dump(mode="json")
    assert c.post("/ai/v1/places/nearby", json={"place": p}).status_code == 200


def test_screenshot_without_ocr_is_config_error(make_client):
    c = make_client()  # 기본 파이프라인: OCR 없음
    r = c.post("/ai/v1/places/resolve/screenshot", files=[("files", ("a.png", b"\x89PNG", "image/png"))])
    assert r.status_code == 503 and r.json()["error"]["code"] == "extractor_unavailable"


def test_register_into_existing_app(monkeypatch):
    from fastapi import FastAPI

    from placeflow.ai_api import register

    monkeypatch.delenv("AI_SERVICE_KEY", raising=False)
    deps.get_settings.cache_clear()
    backend = FastAPI()

    @backend.get("/users/me")
    def me():
        return {"id": 1}

    register(backend, with_health=False)
    backend.dependency_overrides[deps.get_search] = lambda: FakeNaver()
    c = TestClient(backend)
    assert c.get("/users/me").json() == {"id": 1}
    assert c.get("/ai/v1/regions").json()["ok"] is True
    r = c.post("/ai/v1/recommendations/replacements",
               json={"course_places": [JAMSIL[0].model_dump(mode="json")], "index": 3})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_input"

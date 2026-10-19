"""장소 인식(링크·캡션·스크린샷) · 직접 검색 · 주변 놀거리."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from ...v3.api import split_share_text
from ...v3.domain import DomainError
from ...v3.recommend import nearby_places
from ...v3.save_flow import ResolveResult, candidates_from_records, search_candidates
from ..deps import get_pipeline, get_search, get_settings, ocr_gate
from ..schemas import CandidateList, NearbyRequest, Ok, ResolveRequest

router = APIRouter(tags=["장소 인식"])

ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGES = 5


def _is_saved(ids: list[str]):
    s = set(ids)
    return lambda pid: pid in s


@router.post("/places/resolve", response_model=Ok[ResolveResult], summary="링크·캡션 → 장소 후보")
def resolve_link(body: ResolveRequest, search=Depends(get_search)):
    """링크(또는 앱 '공유 → 복사' 문구 전체)·캡션에서 장소를 찾아 **장소별 묶음(groups)** 으로 후보를 돌려줍니다.
    저장하지 않습니다. 사용자가 고른 Place 는 백엔드가 저장합니다."""
    if body.type == "link":
        url, shared = split_share_text(body.url or "")
        if not url:
            raise DomainError("invalid_input", "http(s) 링크나 공유 문구를 붙여넣어 주세요.")
        note = "\n".join(x for x in (shared, (body.note or "").strip()) if x) or None
        out = get_pipeline().run(url, note)
        kind = "link"
    else:
        text = (body.note or body.url or "").strip()
        if not text:
            raise DomainError("invalid_input", "캡션이나 메모를 입력해 주세요.")
        out = get_pipeline().run(text)
        kind = "text"
    res = candidates_from_records(out.records, search, kind, _is_saved(body.saved_place_ids), out.message)
    return Ok[ResolveResult](data=res)


@router.post("/places/resolve/screenshot", response_model=Ok[ResolveResult], summary="스크린샷 → 장소 후보")
def resolve_screenshot(files: list[UploadFile] = File(..., description="이미지 1~5장 (png·jpg·jpeg·webp·gif)"),
                       note: Optional[str] = Form(None, description="함께 붙여넣은 캡션·메모"),
                       saved_place_ids: list[str] = Form(default_factory=list,
                                                         description="이미 저장한 place_id (여러 번 보내기)"),
                       search=Depends(get_search)):
    """multipart/form-data. 여러 장이면 같은 장소의 여러 화면(홈·메뉴·정보 탭)으로 보고 합쳐서 읽습니다."""
    if not files or len(files) > MAX_IMAGES:
        raise DomainError("invalid_input", f"스크린샷은 1~{MAX_IMAGES}장 올려 주세요.")
    limit = get_settings().max_image_mb * 1024 * 1024
    paths: list[str] = []
    try:
        for f in files:
            ext = Path(f.filename or "upload.png").suffix.lower()
            if ext not in ALLOWED_IMG:
                raise DomainError("invalid_input", f"지원하지 않는 이미지 형식입니다: {ext or '(없음)'}")
            data = f.file.read(limit + 1)
            if not data:
                raise DomainError("invalid_input", "빈 이미지 파일이 있어요.")
            if len(data) > limit:
                raise DomainError("invalid_input", f"이미지는 장당 {get_settings().max_image_mb}MB까지 올릴 수 있어요.")
            fd, tmp = tempfile.mkstemp(suffix=ext, prefix="ai_upload_")
            with os.fdopen(fd, "wb") as w:
                w.write(data)
            paths.append(tmp)
        pipe = get_pipeline()
        with ocr_gate():
            out = pipe.run(paths[0], (note or "").strip() or None, more_images=paths[1:] or None)
    finally:
        for p in paths:
            Path(p).unlink(missing_ok=True)
    if not out.records and out.status.value == "failed" and "OCR" in (out.message or ""):
        # 서버에 OCR(tesseract+kor)·비전 LLM 이 없음 → 사용자 탓이 아니므로 설정 오류로 알림
        raise DomainError("extractor_unavailable", out.message)
    res = candidates_from_records(out.records, search, "screenshot", _is_saved(saved_place_ids), out.message)
    return Ok[ResolveResult](data=res)


@router.get("/places/search", response_model=Ok[ResolveResult], summary="직접 검색")
def search_places(q: str = Query(..., min_length=1, max_length=100, description="장소 이름이나 주소"),
                  saved_place_ids: list[str] = Query(default_factory=list),
                  search=Depends(get_search)):
    """네이버 지역검색 결과를 후보로 돌려줍니다 (groups 는 비어 있고 candidates 만 있음)."""
    return Ok[ResolveResult](data=search_candidates(search, q, _is_saved(saved_place_ids)))


@router.post("/places/nearby", response_model=Ok[CandidateList], summary="주변 놀거리")
def nearby(body: NearbyRequest, search=Depends(get_search)):
    """장소 상세 '주변 놀거리': 걸어서 10분 이내의 놀거리·카페 (저장한 장소 먼저). 외부 검색이 실패하면 저장 장소만."""
    pool = [(s.place, s.source) for s in body.saved_places]
    return Ok[CandidateList](data=CandidateList(candidates=nearby_places(body.place, pool, search, body.limit)))

"""OneClickMeet AI 서버 (FastAPI). 상태 없음: 사용자 데이터는 백엔드가 요청에 담아 보내고, 결과만 돌려줍니다.

  python -m placeflow api --port 8001      → http://127.0.0.1:8001/docs (Swagger)
  uvicorn placeflow.ai_api.main:app        (배포 시)
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..v3.domain import DomainError
from ..v3.search import ExternalSearchError
from .deps import Unauthorized, get_search, get_settings, require_key
from .routers import places, recommend
from .schemas import Err, Health

WORKFLOW_VERSION = "1.1"
PREFIX = "/ai/v1"

HTTP_OF = {
    "invalid_input": 400, "unauthorized": 401, "place_not_found": 404,
    "external_api_failed": 502, "extractor_unavailable": 503, "internal": 500,
}
log = logging.getLogger("placeflow.ai_api")

ERROR_RESPONSES = {code: {"model": Err} for code in (400, 401, 404, 502, 503)}


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": {"code": code, "message": message}})


def register(app: FastAPI, prefix: str = PREFIX, *, with_health: bool = True) -> FastAPI:
    """기존 FastAPI 앱(예: 백엔드)에 AI 라우터·인증·에러 봉투를 붙입니다.

        from placeflow.ai_api import register
        register(backend_app)              # → backend_app 에 /ai/v1/* 추가
    """
    auth = [Depends(require_key)]
    app.include_router(places.router, prefix=prefix, dependencies=auth, responses=ERROR_RESPONSES)
    app.include_router(recommend.router, prefix=prefix, dependencies=auth, responses=ERROR_RESPONSES)

    if with_health:
        @app.get("/health", response_model=Health, tags=["상태"])
        def health():
            from ..ocr import tesseract_status

            s = get_settings()
            try:
                search_name = get_search().name
            except ValueError as e:  # 네이버 키 없음 등
                search_name = f"error: {e}"
            return Health(workflow_version=WORKFLOW_VERSION, search_provider=search_name, extractor=s.llm, ocr=s.ocr,
                          ocr_ready=tesseract_status()[0], auth_required=bool(s.api_key))

    @app.exception_handler(DomainError)
    def _domain(_: Request, e: DomainError):
        return _err(HTTP_OF.get(e.code, 422), e.code, e.message)

    @app.exception_handler(ExternalSearchError)
    def _external(_: Request, e: ExternalSearchError):
        return _err(502, "external_api_failed", f"장소 검색을 불러오지 못했어요. ({e})")

    @app.exception_handler(Unauthorized)
    def _unauth(_: Request, __: Unauthorized):
        return _err(401, "unauthorized", "X-AI-Key 헤더가 없거나 올바르지 않습니다.")

    return app


def create_app() -> FastAPI:
    """AI 서버 단독 실행용 앱."""
    from ..envfile import load_env

    load_env()  # 프로젝트 .env (NAVER_CLIENT_ID 등)
    settings = get_settings()
    app = FastAPI(
        title="OneClickMeet AI API",
        version=WORKFLOW_VERSION,
        description="장소 인식(링크·캡션·스크린샷)과 도보 코스 추천. 상태 없음 — 사용자 데이터는 요청에 담아 보냅니다. "
                    "응답은 `{ok, data}` / `{ok:false, error:{code, message}}`.",
    )
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                           allow_headers=["*"])
    register(app)

    # 단독 서버에서만: 요청 검증 오류·예상 못 한 오류도 같은 봉투로 (백엔드 앱의 전역 처리는 건드리지 않음)
    @app.exception_handler(RequestValidationError)
    def _invalid(_: Request, e: RequestValidationError):
        errs = e.errors()[:3]
        msg = "; ".join(f"{'.'.join(str(x) for x in er.get('loc', ())[1:]) or '요청'}: {er.get('msg', '')}"
                        for er in errs)
        return _err(400, "invalid_input", f"요청 형식 오류 — {msg}")

    @app.exception_handler(Exception)
    def _internal(_: Request, e: Exception):
        log.exception("internal error")
        return _err(500, "internal", f"서버 오류가 발생했어요. ({type(e).__name__})")

    return app


app = create_app()

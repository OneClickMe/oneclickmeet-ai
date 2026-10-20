"""오류 → application/problem+json (TRD 부록 A 2.4). 외부 제공자 원문·내부 예외는 응답에 넣지 않고 로그로만 남긴다."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("placeflow.ai_api")

TITLES = {400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 413: "Payload Too Large",
          415: "Unsupported Media Type", 500: "Internal Server Error", 503: "Service Unavailable"}


class ApiProblem(Exception):
    def __init__(self, status: int, code: str, reason: str, detail: str, errors: Optional[list[dict]] = None):
        super().__init__(detail)
        self.status, self.code, self.reason, self.detail, self.errors = status, code, reason, detail, errors


# 내부 DomainError 코드 → (HTTP, code, reason)
DOMAIN_MAP = {
    "invalid_input": (400, "COMMON-0400", "INVALID_INPUT"),
    "place_not_found": (404, "COMMON-0404", "RESOURCE_NOT_FOUND"),
    "extractor_unavailable": (503, "EXTERNAL-0503", "RECOGNIZER_UNAVAILABLE"),
}


def invalid(detail: str, field: Optional[str] = None) -> ApiProblem:
    return ApiProblem(400, "COMMON-0400", "INVALID_INPUT", detail,
                      [{"field": field, "message": detail}] if field else None)


def provider_unavailable() -> ApiProblem:
    return ApiProblem(503, "EXTERNAL-0503", "PROVIDER_UNAVAILABLE",
                      "외부 장소 검색 서비스를 이용할 수 없습니다. 잠시 후 다시 시도해 주세요.")


def problem_response(request: Request, p: ApiProblem) -> JSONResponse:
    body = {"type": "about:blank", "title": TITLES.get(p.status, "Error"), "status": p.status, "detail": p.detail,
            "instance": request.url.path, "code": p.code, "reason": p.reason}
    if p.errors:
        body["errors"] = p.errors
    return JSONResponse(status_code=p.status, content=body, media_type="application/problem+json")

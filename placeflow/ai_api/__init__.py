"""OneClickMeet AI 서버 (FastAPI). 단독 실행: placeflow.ai_api.main:app / 백엔드에 붙이기: register(app)."""


def register(app, prefix: str = "/ai/v1", **kw):
    from .main import register as _register

    return _register(app, prefix, **kw)

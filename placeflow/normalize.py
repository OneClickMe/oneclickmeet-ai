"""정규화·개인정보 마스킹·중복키·임베딩 텍스트."""
from __future__ import annotations

import re

from . import taxonomy
from .models import Address

SIDO_FULL = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시", "광주": "광주광역시",
    "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도", "강원": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도", "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도",
    "경남": "경상남도", "제주": "제주특별자치도",
}


def parse_address(road: str | None, jibun: str | None = None) -> Address:
    src = road or jibun or ""
    toks = src.split()
    sido = sigungu = dong = None
    if toks:
        key = toks[0][:2]
        if key in SIDO_FULL:
            sido = SIDO_FULL[key]
            gu = [t for t in toks[1:3] if re.search(r"(시|군|구)$", t)]
            sigungu = " ".join(gu) or None
    for t in (jibun or "").split():
        if re.search(r"(동|읍|면|가)$", t) and not re.search(r"(시|군|구)$", t):
            dong = t
            break
    return Address(road=road, jibun=jibun, sido=sido, sigungu=sigungu, dong=dong)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_HANDLE = re.compile(r"(?<![\w])@[A-Za-z0-9_.]{2,30}")
_MOBILE = re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)")
_RRN = re.compile(r"(?<!\d)\d{6}-?[1-8]\d{6}(?!\d)")  # 주민등록번호 형식


def is_personal_phone(phone: str | None) -> bool:
    """휴대폰(01x) 번호는 개인 번호일 수 있어 장소 전화번호로 저장하지 않습니다."""
    return bool(phone) and bool(re.match(r"^\s*01[016789]", phone))


def mask_pii(text: str | None, limit: int = 1000) -> str | None:
    """저장용 원문 발췌에서 주민번호 형식·이메일·@계정·휴대폰 번호를 가립니다. (가게 유선번호 02-, 031- 등은 유지)"""
    if not text:
        return text
    t = _RRN.sub("[id]", text)
    t = _EMAIL.sub("[email]", t)
    t = _HANDLE.sub("@***", t)
    t = _MOBILE.sub("010-****-****", t)
    return t[:limit]


def dedupe_key(name: str, branch: str | None, sigungu: str | None,
               naver_id: str | None, kakao_id: str | None) -> str:
    if kakao_id:
        return f"kakao:{kakao_id}"
    if naver_id:
        return f"naver:{naver_id}"
    base = re.sub(r"\s+", "", f"{name}{branch or ''}").lower()
    return f"name:{base}@{(sigungu or 'unknown').replace(' ', '')}"


def embedding_text(rec) -> str:
    c = rec.classification
    region = " ".join(x for x in (rec.place.address.sido, rec.place.address.sigungu, rec.place.address.dong) if x)
    menus = ", ".join(m.name for m in rec.details.signature_menus[:5])
    parts = [
        f"{rec.place.name}{' ' + rec.place.branch if rec.place.branch else ''}",
        f"{c.primary_label}/{c.sub_label or ''}",
        region,
        " ".join(f"#{t}" for t in c.tags + c.free_tags),
        f"가격대 {taxonomy.PRICE_LEVELS[rec.details.price_level]}" if rec.details.price_level else "",
        f"대표메뉴 {menus}" if menus else "",
        rec.content.summary or "",
        " / ".join(rec.content.highlights[:3]),
    ]
    return " | ".join(p for p in parts if p)

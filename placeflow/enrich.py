"""추출 결과(ExtractedPlace) → 코스 추천에 쓰는 Details(v0.2) + 필드별 출처.

규칙 기반 기본값(체류시간·실내 여부·가격대→비용)은 'default' 출처로 표시해서,
나중에 실제 정보(OCR/링크)가 들어오면 덮어쓸 수 있게 합니다.
"""
from __future__ import annotations

from . import hours as hours_mod
from .models import Details, ExtractedPlace, FieldSource

# (대분류, 소분류) → 평균 체류시간(분). 소분류가 없으면 대분류 기본값.
STAY_MINUTES: dict[tuple[str, str | None], int] = {
    ("restaurant", None): 80, ("restaurant", "fast_food"): 40, ("restaurant", "brunch"): 70,
    ("restaurant", "meat_bbq"): 90, ("restaurant", "japanese"): 90, ("restaurant", "western"): 90,
    ("cafe", None): 60, ("cafe", "bakery"): 30, ("cafe", "themed"): 90,
    ("bar", None): 100, ("bar", "pocha"): 90,
    ("culture", None): 80, ("culture", "popup"): 40, ("culture", "performance"): 130, ("culture", "cinema"): 140,
    ("culture", "bookstore"): 40, ("culture", "museum"): 100,
    ("activity", None): 90, ("activity", "workshop"): 120, ("activity", "escape_room"): 80,
    ("activity", "photo"): 40, ("activity", "theme_park"): 240, ("activity", "game"): 60,
    ("nature", None): 60, ("nature", "scenic"): 40, ("nature", "beach"): 90,
    ("shopping", None): 50, ("shopping", "market"): 70,
    ("stay", None): 0, ("other", None): 60,
}

INDOOR_DEFAULT: dict[str, bool | None] = {
    "restaurant": True, "cafe": True, "bar": True, "culture": True, "activity": True,
    "nature": False, "shopping": True, "stay": True, "other": None,
}

# 가격대(1~4) → 1인 비용 대표값(원)
PRICE_LEVEL_COST = {1: 8000, 2: 20000, 3: 45000, 4: 80000}


def stay_minutes(primary: str, sub: str | None) -> int:
    return STAY_MINUTES.get((primary, sub)) or STAY_MINUTES.get((primary, None), 60)


def build_details(p: ExtractedPlace, primary: str, sub: str | None, source: str,
                  conf: float | None = None) -> tuple[Details, dict[str, FieldSource]]:
    prov: dict[str, FieldSource] = {}

    def mark(field: str, src: str = source, c: float | None = conf):
        prov[field] = FieldSource(source=src, confidence=c)

    # 영업시간: 원문 + 휴무/브레이크/라스트오더를 합쳐서 구조화
    hours_text = " / ".join(x for x in (p.opening_hours_text, p.closed_days_text,
                                         f"브레이크타임 {p.break_time_text}" if p.break_time_text else None,
                                         f"라스트오더 {p.last_order_text}" if p.last_order_text else None) if x)
    wh = hours_mod.parse_hours(hours_text) if hours_text else None
    if wh:
        mark("opening_hours", c=(conf or 0.5) * (0.6 if wh.partial else 1.0))

    cost = p.est_cost_per_person
    if cost:
        mark("est_cost_per_person")
    elif p.price_level:
        cost = PRICE_LEVEL_COST[p.price_level]
        mark("est_cost_per_person", "default:price_level", 0.4)

    stay = p.stay_minutes_hint
    if stay:
        mark("stay_minutes")
    else:
        stay = stay_minutes(primary, sub)
        mark("stay_minutes", "default:category", 0.5)

    indoor = p.indoor
    if indoor is None:
        if "실외" in p.tags or "루프탑" in p.tags:
            indoor = False
        elif "실내" in p.tags:
            indoor = True
        else:
            indoor = INDOOR_DEFAULT.get(primary)
        if indoor is not None:
            mark("indoor", "default:category", 0.5)
    else:
        mark("indoor")

    res_required = None
    rt = (p.reservation_text or "") + " " + " ".join(p.tags)
    if "예약필수" in p.tags or "필수" in rt or "예약제" in rt:
        res_required = True
    elif "예약 불가" in rt or p.reservation_method == "walk_in":
        res_required = False

    waiting = None
    blob = " ".join(p.cautions + p.tags)
    if "웨이팅" in blob:
        waiting = "long" if any(k in blob for k in ("오픈런", "1시간", "긴 웨이팅")) else "some"

    for f, v in (("rating", p.rating), ("review_count", p.review_count), ("nearest_station", p.nearest_station_text),
                 ("parking", p.parking_text), ("reservation_method", p.reservation_method)):
        if v not in (None, ""):
            mark(f)
    if p.amenities:
        mark("amenities")
    if p.signature_menus:
        mark("signature_menus")

    d = Details(
        signature_menus=p.signature_menus, price_level=p.price_level, price_text=p.price_text,
        est_cost_per_person=cost, opening_hours_text=p.opening_hours_text, closed_days_text=p.closed_days_text,
        opening_hours=wh, reservation_text=p.reservation_text, reservation_method=p.reservation_method,
        reservation_required=res_required, waiting_level=waiting, stay_minutes=stay, indoor=indoor,
        rating=p.rating, review_count=p.review_count, nearest_station=p.nearest_station_text,
        parking=p.parking_text, amenities=p.amenities,
    )
    return d, prov

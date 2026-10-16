"""도보 거리·시간 추정 (V3 는 도보 코스만).

직선거리(haversine) × 우회계수 1.3 ÷ 보행속도 4.5km/h. 결과는 '예상 도보시간'(추정)입니다.
"""
from __future__ import annotations

import math

WALK_KMH = 4.5
DETOUR = 1.3
MAX_LEG_MIN = 10        # V3: 장소 사이는 걸어서 10분 이내
ANCHOR_RADIUS_M = 1000  # V3: 기준 장소(지역) 반경 약 1km


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(h))


def walk_minutes(a: tuple[float, float], b: tuple[float, float]) -> int:
    """예상 도보시간(분, 올림). 같은 위치면 1분."""
    km = distance_m(a, b) / 1000 * DETOUR
    return max(1, math.ceil(km / WALK_KMH * 60))


def walkable(a: tuple[float, float], b: tuple[float, float], limit: int = MAX_LEG_MIN) -> bool:
    return walk_minutes(a, b) <= limit

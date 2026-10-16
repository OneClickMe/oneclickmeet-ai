"""지원 지역 (V3 데모: 6곳). 좌표는 각 지역 중심의 근사값입니다 — 운영 시 기획/백엔드에서 확정하세요."""
from __future__ import annotations

from dataclasses import dataclass

from .walking import distance_m


@dataclass(frozen=True)
class Region:
    region_id: str
    name: str          # 화면 표시 이름
    area_query: str    # 외부 검색어 앞에 붙일 지역명
    lat: float
    lng: float
    radius_m: int = 1200  # 이 반경 안이면 '지원 지역'


REGIONS: list[Region] = [
    Region("yeonnam", "연남", "연남동", 37.5626, 126.9255),
    Region("seochon", "서촌", "서촌", 37.5794, 126.9696),
    Region("hyehwa", "혜화", "혜화", 37.5822, 127.0019),
    Region("jamsil", "잠실", "잠실", 37.5110, 127.0980, 1500),
    Region("sungshin", "성신여대역", "성신여대", 37.5927, 127.0167),
    Region("hansung", "한성대입구역", "한성대입구", 37.5884, 127.0062),
]
BY_ID = {r.region_id: r for r in REGIONS}


def get_region(region_id: str) -> Region | None:
    return BY_ID.get(region_id)


def region_of(lat: float, lng: float) -> Region | None:
    """좌표가 속한 지원 지역 (가장 가까운 곳). 없으면 None → '지원 지역 밖'."""
    best = None
    for r in REGIONS:
        d = distance_m((lat, lng), (r.lat, r.lng))
        if d <= r.radius_m and (best is None or d < best[0]):
            best = (d, r)
    return best[1] if best else None

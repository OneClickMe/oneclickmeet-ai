"""코스 추천용 카테고리 코드 7개 (v2 확정).

  MEAL      맛집 (음식점, 술집 제외)
  CAFE      카페·디저트
  BAR       술집·바·이자카야
  ACTIVITY  방탈출·보드게임·공방·포토부스 등 체험
  CULTURE   전시·공연·미술관·도서관 (카카오 문화시설 CT1)
  WALK      공원·산책로·전망·관광명소 (카카오 관광명소 AT4)
  SHOPPING  소품샵·편집숍·시장
숙박(stay)·기타(other)는 코스 후보에서 빠진다.
"""
from __future__ import annotations

from typing import Literal, Optional

CategoryCode = Literal["MEAL", "CAFE", "BAR", "ACTIVITY", "CULTURE", "WALK", "SHOPPING"]
CODES: tuple[str, ...] = ("MEAL", "CAFE", "BAR", "ACTIVITY", "CULTURE", "WALK", "SHOPPING")

LABELS = {"MEAL": "맛집", "CAFE": "카페", "BAR": "술집", "ACTIVITY": "놀거리", "CULTURE": "전시·문화",
          "WALK": "산책", "SHOPPING": "쇼핑"}

# 내부 분류(taxonomy 대분류) → 코드
PRIMARY_TO_CODE = {"restaurant": "MEAL", "cafe": "CAFE", "bar": "BAR", "activity": "ACTIVITY",
                   "culture": "CULTURE", "nature": "WALK", "shopping": "SHOPPING"}
CODE_TO_PRIMARY = {v: k for k, v in PRIMARY_TO_CODE.items()}

# 외부 검색: 카카오 카테고리 그룹(있으면) + 검색어. 네이버·데모는 '지역명 + 검색어'로 씀
SEARCH_PLAN: dict[str, dict] = {
    "MEAL": {"kakao_group": "FD6", "keywords": ["맛집"]},
    "CAFE": {"kakao_group": "CE7", "keywords": ["카페", "디저트"]},
    "BAR": {"kakao_group": None, "keywords": ["술집", "이자카야", "와인바"]},
    "ACTIVITY": {"kakao_group": None, "keywords": ["방탈출", "보드게임카페", "공방", "포토부스", "놀거리"]},
    "CULTURE": {"kakao_group": "CT1", "keywords": ["전시", "미술관"]},
    "WALK": {"kakao_group": "AT4", "keywords": ["공원", "산책"]},
    "SHOPPING": {"kakao_group": None, "keywords": ["소품샵", "편집숍"]},
}

# 카카오 category_group_code → 내부 분류 (category_name 글자로 못 정할 때만 사용)
KAKAO_GROUP_TO_PRIMARY = {"FD6": "restaurant", "CE7": "cafe", "CT1": "culture", "AT4": "nature", "AD5": "stay"}


def code_of(primary: Optional[str]) -> Optional[str]:
    return PRIMARY_TO_CODE.get(primary or "")


def label_of(code: Optional[str]) -> Optional[str]:
    return LABELS.get(code or "")

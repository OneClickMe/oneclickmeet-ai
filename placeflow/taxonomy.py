"""카테고리 택소노미 (단일 출처).

- PRIMARY: 대분류 → 소분류 목록
- TAGS: 커플 데이트 관점 태그 (그룹별 고정 어휘)
- PRICE_LEVELS: 1인 기준 가격대
- 외부 API 카테고리(카카오 코드, 네이버 카테고리 문자열) → 대분류 매핑

수정은 이 파일에서만 하고, `python -m placeflow export-schema` 로 schema/ 폴더를 갱신합니다.
"""
from __future__ import annotations

PRIMARY: dict[str, dict] = {
    "restaurant": {
        "label": "맛집",
        "sub": {
            "korean": "한식", "meat_bbq": "고기·구이", "seafood": "해산물",
            "japanese": "일식", "chinese": "중식", "western": "양식",
            "asian": "아시안", "brunch": "브런치", "fusion": "퓨전",
            "fast_food": "분식·패스트푸드", "chicken": "치킨", "other": "기타",
        },
    },
    "cafe": {
        "label": "카페·디저트",
        "sub": {
            "dessert": "디저트", "bakery": "베이커리", "roastery": "로스터리",
            "tea": "찻집", "themed": "테마카페", "other": "기타",
        },
    },
    "bar": {
        "label": "술집·바",
        "sub": {
            "wine_bar": "와인바", "cocktail_bar": "칵테일바", "izakaya": "이자카야",
            "pub": "펍·호프", "pocha": "포차", "brewery": "브루어리", "other": "기타",
        },
    },
    "culture": {
        "label": "전시·문화",
        "sub": {
            "exhibition": "전시", "museum": "박물관·미술관", "popup": "팝업스토어",
            "performance": "공연", "cinema": "영화관", "bookstore": "서점",
            "other": "기타",
        },
    },
    "activity": {
        "label": "액티비티·체험",
        "sub": {
            "workshop": "공방·원데이클래스", "escape_room": "방탈출",
            "photo": "사진관·포토부스", "sports": "스포츠", "theme_park": "테마파크",
            "game": "게임·오락", "other": "기타",
        },
    },
    "nature": {
        "label": "자연·산책",
        "sub": {
            "park": "공원", "beach": "바다", "mountain": "산", "garden": "정원·수목원",
            "scenic": "뷰포인트", "other": "기타",
        },
    },
    "shopping": {
        "label": "쇼핑",
        "sub": {"shop": "소품샵·편집숍", "market": "시장", "mall": "쇼핑몰", "other": "기타"},
    },
    "stay": {
        "label": "숙소",
        "sub": {
            "hotel": "호텔", "pension": "펜션", "glamping": "글램핑·캠핑",
            "guesthouse": "게스트하우스·한옥스테이", "other": "기타",
        },
    },
    "other": {"label": "기타", "sub": {"other": "기타"}},
}

TAGS: dict[str, list[str]] = {
    "mood": ["감성", "아늑한", "뷰맛집", "힙한", "조용한", "고급스러운", "레트로", "이색적인", "야경"],
    "occasion": ["기념일", "첫데이트", "데일리", "생일", "프로포즈"],
    "setting": ["실내", "실외", "루프탑", "오션뷰", "반려동물동반"],
    "practical": ["예약필수", "웨이팅있음", "주차가능", "늦게까지영업", "콜키지가능"],
}
ALL_TAGS: list[str] = [t for group in TAGS.values() for t in group]

PRICE_LEVELS: dict[int, str] = {
    1: "1인 1만원 미만",
    2: "1인 1~3만원",
    3: "1인 3~6만원",
    4: "1인 6만원 이상",
}

# 카카오 category_group_code → (대분류, 소분류)
KAKAO_GROUP_MAP: dict[str, tuple[str, str | None]] = {
    "FD6": ("restaurant", None),
    "CE7": ("cafe", None),
    "CT1": ("culture", None),
    "AT4": ("nature", "scenic"),
    "AD5": ("stay", None),
}

# 키워드 → (대분류, 소분류). 네이버 category 문자열, 카카오 category_name, 본문 모두에 사용.
# 위에서부터 먼저 맞는 규칙이 이깁니다(구체적인 것을 위에).
KEYWORD_RULES: list[tuple[str, str, str]] = [
    ("와인", "bar", "wine_bar"), ("칵테일", "bar", "cocktail_bar"), ("이자카야", "bar", "izakaya"),
    ("포차", "bar", "pocha"), ("브루어리", "bar", "brewery"), ("맥주", "bar", "pub"),
    ("호프", "bar", "pub"), 
    ("베이커리", "cafe", "bakery"), ("빵", "cafe", "bakery"), ("디저트", "cafe", "dessert"),
    ("케이크", "cafe", "dessert"), ("로스터리", "cafe", "roastery"), ("찻집", "cafe", "tea"),
    ("전통차", "cafe", "tea"), ("애견카페", "cafe", "themed"), ("보드게임카페", "cafe", "themed"),
    ("팝업", "culture", "popup"), ("전시", "culture", "exhibition"), ("갤러리", "culture", "exhibition"),
    ("미술관", "culture", "museum"), ("박물관", "culture", "museum"), ("공연", "culture", "performance"),
    ("뮤지컬", "culture", "performance"), ("영화관", "culture", "cinema"), ("서점", "culture", "bookstore"),
    ("공방", "activity", "workshop"), ("원데이클래스", "activity", "workshop"),
    ("방탈출", "activity", "escape_room"), ("사진관", "activity", "photo"),
    ("포토부스", "activity", "photo"), ("테마파크", "activity", "theme_park"),
    ("놀이공원", "activity", "theme_park"), ("볼링", "activity", "sports"), ("클라이밍", "activity", "sports"),
    ("오락실", "activity", "game"), ("보드카페", "activity", "game"), ("만화카페", "activity", "game"),
    ("VR", "activity", "game"), ("인생네컷", "activity", "photo"),
    ("수목원", "nature", "garden"), ("정원", "nature", "garden"), ("해변", "nature", "beach"),
    ("해수욕장", "nature", "beach"), ("공원", "nature", "park"), ("전망대", "nature", "scenic"),
    ("호텔", "stay", "hotel"), ("펜션", "stay", "pension"), ("글램핑", "stay", "glamping"),
    ("캠핑", "stay", "glamping"), ("한옥스테이", "stay", "guesthouse"), ("풀빌라", "stay", "pension"), ("독채", "stay", "pension"),
    ("리조트", "stay", "hotel"), ("스테이", "stay", "other"), ("숙소", "stay", "other"), ("게스트하우스", "stay", "guesthouse"),
    ("소품샵", "shopping", "shop"), ("편집숍", "shopping", "shop"), ("시장", "shopping", "market"),
    ("고기", "restaurant", "meat_bbq"), ("삼겹살", "restaurant", "meat_bbq"), ("갈비", "restaurant", "meat_bbq"),
    ("통닭", "restaurant", "chicken"), ("치킨", "restaurant", "chicken"), ("치맥", "restaurant", "chicken"),
    ("제육", "restaurant", "korean"), ("백반", "restaurant", "korean"), ("국밥", "restaurant", "korean"),
    ("주꾸미", "restaurant", "seafood"), ("쭈꾸미", "restaurant", "seafood"), ("낙지", "restaurant", "seafood"),
    ("이탈리아", "restaurant", "western"), ("요리주점", "bar", "izakaya"), ("보드게임", "activity", "game"),
    ("숲길", "nature", "park"), ("산책", "nature", "park"), ("명소", "nature", "scenic"), ("소품", "shopping", "shop"),
    ("오마카세", "restaurant", "japanese"), ("스시", "restaurant", "japanese"), ("초밥", "restaurant", "japanese"),
    ("라멘", "restaurant", "japanese"), ("일식", "restaurant", "japanese"), ("중식", "restaurant", "chinese"),
    ("파스타", "restaurant", "western"), ("스테이크", "restaurant", "western"), ("양식", "restaurant", "western"),
    ("이탈리안", "restaurant", "western"), ("태국", "restaurant", "asian"), ("베트남", "restaurant", "asian"),
    ("쌀국수", "restaurant", "asian"), ("브런치", "restaurant", "brunch"), ("해산물", "restaurant", "seafood"),
    ("횟집", "restaurant", "seafood"), ("한식", "restaurant", "korean"), ("떡볶이", "restaurant", "fast_food"),
    ("분식", "restaurant", "fast_food"), ("버거", "restaurant", "fast_food"),
    # ↓ 일반 키워드는 맨 끝 (예: "방탈출카페"가 카페로 잡히지 않도록)
    ("술집", "bar", "other"), ("주점", "bar", "other"), ("바(BAR)", "bar", "other"),
    ("카페", "cafe", "other"), ("맛집", "restaurant", "other"), ("음식점", "restaurant", "other"),
]

# 본문 키워드 → 태그 (휴리스틱 추출기, LLM 결과 보정에 사용)
TAG_KEYWORDS: dict[str, list[str]] = {
    "감성": ["감성"], "아늑한": ["아늑"], "뷰맛집": ["뷰맛집", "뷰가", "통창"], "힙한": ["힙한", "힙플"],
    "조용한": ["조용"], "고급스러운": ["고급", "파인다이닝"], "레트로": ["레트로", "빈티지"],
    "이색적인": ["이색"], "야경": ["야경"],
    "기념일": ["기념일", "100일", "1주년", "주년"], "첫데이트": ["첫데이트", "소개팅"],
    "생일": ["생일"], "프로포즈": ["프로포즈", "청혼"], "데일리": ["데일리", "가볍게"],
    "실외": ["야외", "테라스"], "루프탑": ["루프탑", "옥상"], "오션뷰": ["오션뷰", "바다뷰"],
    "반려동물동반": ["애견동반", "반려견 동반", "반려동물 동반"],
    "예약필수": ["예약필수", "예약 필수", "예약제", "캐치테이블"], "웨이팅있음": ["웨이팅", "줄 서"],
    "주차가능": ["주차가능", "주차 가능", "주차장 있"], "늦게까지영업": ["새벽", "늦게까지", "24시"],
    "콜키지가능": ["콜키지"],
}


def is_valid(primary: str, sub: str | None) -> bool:
    if primary not in PRIMARY:
        return False
    return sub is None or sub in PRIMARY[primary]["sub"]


_GENERIC = {"술집", "주점", "바(BAR)", "카페", "맛집", "음식점"}
SHORT_TEXT = 30  # 이 길이 이하(상호명·카테고리 문자열)는 '마지막' 키워드가 핵심어


# 두 글자 분류어가 다른 낱말 한가운데 끼어 있으면 무시 (예: '일일식탁' 안의 '일식')
_EMBED_SENSITIVE = {"일식", "중식", "한식", "양식"}


def _free_pos(text: str, kw: str) -> int:
    """kw 가 앞뒤 모두 한글에 붙어 있지 않은 첫 위치 (없으면 -1). '일식당'·'정통일식'은 허용, '일일식탁'은 제외."""
    start = 0
    while True:
        pos = text.find(kw, start)
        if pos < 0:
            return -1
        before = text[pos - 1] if pos > 0 else ""
        after = text[pos + len(kw)] if pos + len(kw) < len(text) else ""
        hangul = lambda ch: "가" <= ch <= "힣"  # noqa: E731
        if not (hangul(before) and hangul(after)) or after in ("당", "집"):
            return pos
        start = pos + 1


def _best_rule(text: str, rules) -> tuple[str, str, str] | None:
    """한 텍스트 안에서 규칙 하나를 고릅니다.

    짧은 텍스트(상호명 등)는 한국어 명사구의 머리말이 뒤에 오므로 가장 뒤에 나온 키워드를,
    긴 본문은 가장 먼저 나온 키워드를 씁니다. 구체 키워드가 있으면 일반 키워드(카페/맛집 등)보다 우선합니다.
    """
    hits = []
    for rule in rules:
        pos = text.find(rule[0])
        if pos >= 0 and rule[0] in _EMBED_SENSITIVE:
            pos = _free_pos(text, rule[0])
        if pos >= 0:
            hits.append((rule[0] in _GENERIC, pos + len(rule[0]), pos, rule))
    if not hits:
        return None
    specific = [h for h in hits if not h[0]] or hits
    if len(text) <= SHORT_TEXT:
        return max(specific, key=lambda h: h[1])[3]
    return min(specific, key=lambda h: h[2])[3]


def classify_text(*texts: str | None) -> tuple[str, str] | None:
    """텍스트들(우선순위 순서)에서 대분류를 정하고, 같은 대분류 안에서 가장 구체적인 소분류를 찾습니다.

    예: 이름 "카페 온담" + 본문 "디저트" → ("cafe", "dessert"),  "바다정원 글램핑" → ("stay", "glamping")
    """
    texts = [t for t in texts if t]
    for text in texts:
        rule = _best_rule(text, KEYWORD_RULES)
        if not rule:
            continue
        primary, sub = rule[1], rule[2]
        if sub != "other":
            return primary, sub
        same = [r for r in KEYWORD_RULES if r[1] == primary and r[2] != "other"]
        for t in texts:
            r2 = _best_rule(t, same)
            if r2:
                return primary, r2[2]
        return primary, "other"
    return None


def tags_from_text(text: str) -> list[str]:
    found = []
    for tag, kws in TAG_KEYWORDS.items():
        if any(k in text for k in kws):
            found.append(tag)
    return found


def as_dict() -> dict:
    return {
        "primary": PRIMARY,
        "tags": TAGS,
        "price_levels": PRICE_LEVELS,
        "kakao_group_map": {k: list(v) for k, v in KAKAO_GROUP_MAP.items()},
        "keyword_rules": [list(r) for r in KEYWORD_RULES],
    }


def prompt_block() -> str:
    """LLM 프롬프트에 넣을 택소노미 설명."""
    lines = ["[대분류.소분류]"]
    for p, info in PRIMARY.items():
        subs = ", ".join(f"{k}({v})" for k, v in info["sub"].items())
        lines.append(f"- {p}({info['label']}): {subs}")
    lines.append("[태그 — 이 목록에서만 고르세요]")
    for g, tags in TAGS.items():
        lines.append(f"- {g}: {', '.join(tags)}")
    lines.append("[가격대 price_level]")
    for k, v in PRICE_LEVELS.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)

"""평가용 오프라인 픽스처 생성기.

※ 모든 장소·주소·전화번호는 **가상**입니다. 실제 가게와 무관합니다.
실행: python eval/make_fixtures.py  (Pillow 와 한글 폰트가 있으면 캡쳐 PNG도 만듭니다)
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
FIX = HERE / "fixtures"
PAGES = FIX / "pages"
IMAGES = FIX / "images"

# ------------------------------------------------------------------ 링크 픽스처 (HTML 스냅샷)
IG_OK = """<html><head>
<meta property="og:title" content="데이트로그 on Instagram: &quot;연남동 숨은 와인바 🍷&quot;">
<meta property="og:description" content="1,204 likes, 88 comments - datelog_kr on September 2, 2026: &quot;📍비노 루체 연남점 서울 마포구 성미산로 77 지하1층
분위기 미쳤어요… 조용하고 아늑해서 기념일 데이트로 딱🥂 콜키지 가능!
내추럴 와인 글라스 14,000원 / 트러플 감자튀김 18,000원
영업 18:00~02:00 (일요일 휴무) 예약 필수
#연남동와인바 #와인바추천 #커플데이트 #기념일&quot;.">
</head><body></body></html>"""

NAVER_BLOG_SINGLE = """<html><head>
<meta property="og:title" content="[성수 데이트] 통창 뷰 디저트카페 카페 온담 성수점 내돈내산 후기">
<meta property="og:description" content="성수동 서울숲 근처 디저트 카페 카페 온담 다녀왔어요">
</head><body>
<div class="blog_header">이웃추가 @sol_writes</div>
<div class="se-main-container">
<p>남자친구랑 100일 기념으로 다녀온 카페 온담 성수점 후기예요 ☕</p>
<p>📍 카페 온담 성수점</p>
<p>주소 : 서울 성동구 서울숲2길 18 2층</p>
<p>영업시간 : 11:00 - 22:00 / 매주 월요일 휴무</p>
<p>전화 : 02-0000-1234</p>
<p>딸기 생크림 케이크 8,500원 · 아인슈페너 6,500원</p>
<p>통창 너머로 서울숲이 보여서 뷰맛집이에요. 주말엔 웨이팅 있으니 평일 추천!</p>
<p>레터링 케이크는 3일 전 예약 필수래요.</p>
<p>#성수카페 #서울숲카페 #디저트맛집 #기념일카페</p>
</div>
<script>var x = "ignore me";</script>
</body></html>"""

NAVER_BLOG_MULTI = """<html><head>
<meta property="og:title" content="을지로·종로 실내 데이트 코스 3곳 정리 (비 오는 날 추천)">
<meta property="og:description" content="비 오는 날 커플 실내 데이트 코스">
</head><body><div class="se-main-container">
<p>비 오는 주말, 실내에서 하루 종일 놀 수 있는 코스로 정리했어요!</p>
<p>1. 오후 2시 – 반지공방 은솔</p>
<p>📍반지공방 은솔 서울 중구 수표로 21 3층</p>
<p>커플링 원데이클래스 2인 120,000원, 2시간 소요. 예약제로만 운영돼요.</p>
<p>2. 오후 5시 – 전시</p>
<p>📍갤러리 빛결 서울 종로구 삼일대로 300</p>
<p>미디어아트 전시 입장료 15,000원. 사진 찍기 좋은 이색 데이트!</p>
<p>3. 저녁 – 이자카야</p>
<p>📍이자카야 달밤 서울 중구 을지로 120 1층</p>
<p>모둠 사시미 39,000원, 하이볼 8,000원. 레트로 감성, 웨이팅 있음. 새벽 1시까지 영업.</p>
</div></body></html>"""

NAVER_PLACE = """<html><head>
<meta property="og:title" content="바다정원 글램핑 : 네이버">
<meta property="og:description" content="강원 강릉시 사천면 해안로 900 · 글램핑,캠핑">
<title>바다정원 글램핑 : 네이버</title>
</head><body><div id="app-root"></div></body></html>"""

PAGES_INDEX = {
    "https://www.instagram.com/p/FAKE001/": {"file": "ig_ok.html"},
    "https://www.instagram.com/reel/FAKE002/": {"file": None, "status": 200,
                                                "final_url": "https://www.instagram.com/accounts/login/"},
    "https://m.blog.naver.com/fakeblog/220000000001": {"file": "naver_blog_single.html"},
    "https://m.blog.naver.com/fakeblog/220000000002": {"file": "naver_blog_multi.html"},
    "https://naver.me/FAKE05": {"file": None, "status": 200,
                                "final_url": "https://m.place.naver.com/accommodation/1900000005/home"},
    "https://m.place.naver.com/accommodation/1900000005/home": {"file": "naver_place.html"},
}

# ------------------------------------------------------------------ 캡쳐 이미지 픽스처 (OCR 텍스트)
IMAGES_TEXT = {
    "i1_insta_cafe.png": """datelog_kr
📍 모모 베이커리 연남
서울 마포구 동교로 250 1층
소금빵 3,800원 크루아상 4,500원
오픈런 필수… 웨이팅 30분 각오하세요
반려견 동반 가능한 테라스 있어요 🐶
#연남동빵집 #소금빵맛집""",
    "i2_naver_place.png": """이자카야 달밤
이자카야 · 리뷰 1,204
서울 중구 을지로 120 1층
영업 중 · 17:00~01:00
02-0000-5678
모둠 사시미 39,000원
하이볼 8,000원""",
    "i3_story_popup.png": """✨ 팝업 오픈 ✨
포근곰 팝업스토어
10.1 ~ 10.31
서울 성동구 성수이로 88
굿즈 + 포토존 / 사전예약 필수
@pogeun_official""",
    "i4_escape.png": """홍대 방탈출 추천 🔐
상호 : 미스터리룸 홍대점
서울 마포구 와우산로 33 지하1층
2인 44,000원 / 60분 테마
공포 테마는 커플 비추 ㅋㅋ 첫데이트로는 감성 테마 추천""",
    "i5_selfie.png": """오늘도 행복한 하루 💕
우리 300일 🎉
@me_and_you_""",
}

# ------------------------------------------------------------------ 지도 API 대체 (가상 장소 DB)
GEO_PLACES = [
    {"id": "K1001", "name": "비노 루체 연남점", "category": "음식점 > 술집 > 와인바", "kakao_group": "FD6",
     "road_address": "서울 마포구 성미산로 77", "jibun_address": "서울 마포구 연남동 239-1",
     "lat": 37.5631, "lng": 126.9234, "phone": "02-0000-1111", "url": "https://place.map.kakao.com/K1001"},
    {"id": "K1002", "name": "카페 온담 성수점", "category": "음식점 > 카페 > 디저트카페", "kakao_group": "CE7",
     "road_address": "서울 성동구 서울숲2길 18", "jibun_address": "서울 성동구 성수동1가 685-1",
     "lat": 37.5470, "lng": 127.0410, "phone": "02-0000-1234", "url": "https://place.map.kakao.com/K1002"},
    {"id": "K1003", "name": "카페 온담 망원점", "category": "음식점 > 카페", "kakao_group": "CE7",
     "road_address": "서울 마포구 포은로 10", "jibun_address": "서울 마포구 망원동 400-1",
     "lat": 37.5560, "lng": 126.9050, "phone": "02-0000-4321", "url": "https://place.map.kakao.com/K1003"},
    {"id": "K1004", "name": "반지공방 은솔", "category": "가정,생활 > 공방", "kakao_group": None,
     "road_address": "서울 중구 수표로 21", "jibun_address": "서울 중구 저동2가 1-1",
     "lat": 37.5650, "lng": 126.9900, "phone": None, "url": "https://place.map.kakao.com/K1004"},
    {"id": "K1005", "name": "갤러리 빛결", "category": "문화,예술 > 갤러리", "kakao_group": "CT1",
     "road_address": "서울 종로구 삼일대로 300", "jibun_address": "서울 종로구 낙원동 1-1",
     "lat": 37.5720, "lng": 126.9880, "phone": None, "url": "https://place.map.kakao.com/K1005"},
    {"id": "K1006", "name": "이자카야 달밤", "category": "음식점 > 술집 > 일본식주점", "kakao_group": "FD6",
     "road_address": "서울 중구 을지로 120", "jibun_address": "서울 중구 을지로3가 1-1",
     "lat": 37.5660, "lng": 126.9920, "phone": "02-0000-5678", "url": "https://place.map.kakao.com/K1006"},
    {"id": "K1007", "name": "바다정원 글램핑", "category": "여행 > 숙박 > 야영,캠핑장", "kakao_group": "AD5",
     "road_address": "강원특별자치도 강릉시 사천면 해안로 900", "jibun_address": "강원 강릉시 사천면 산대월리 1",
     "lat": 37.8400, "lng": 128.8700, "phone": None, "url": "https://place.map.kakao.com/K1007"},
    {"id": "K1008", "name": "모모 베이커리", "category": "음식점 > 간식 > 제과,베이커리", "kakao_group": "CE7",
     "road_address": "서울 마포구 동교로 250", "jibun_address": "서울 마포구 연남동 1-1",
     "lat": 37.5610, "lng": 126.9250, "phone": None, "url": "https://place.map.kakao.com/K1008"},
    {"id": "K1009", "name": "미스터리룸 홍대점", "category": "가정,생활 > 여가시설 > 방탈출카페", "kakao_group": None,
     "road_address": "서울 마포구 와우산로 33", "jibun_address": "서울 마포구 서교동 1-1",
     "lat": 37.5500, "lng": 126.9230, "phone": None, "url": "https://place.map.kakao.com/K1009"},
    {"id": "K1010", "name": "포근곰 팝업스토어", "category": "문화,예술 > 팝업스토어", "kakao_group": None,
     "road_address": "서울 성동구 성수이로 88", "jibun_address": "서울 성동구 성수동2가 1-1",
     "lat": 37.5440, "lng": 127.0560, "phone": None, "url": "https://place.map.kakao.com/K1010"},
]

# ------------------------------------------------------------------ 정답셋
DATASET = [
    {"id": "L1_instagram_ok", "input": "https://www.instagram.com/p/FAKE001/",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "비노 루체", "primary_category": "bar", "sub_category": "wine_bar", "sigungu": "마포구",
          "tags_any": ["기념일", "아늑한", "콜키지가능", "예약필수"]}]}},
    {"id": "L2_instagram_blocked", "input": "https://www.instagram.com/reel/FAKE002/",
     "expected": {"status_in": ["needs_user_input"], "places": []}},
    {"id": "L3_naver_blog_single", "input": "https://blog.naver.com/fakeblog/220000000001",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "카페 온담", "primary_category": "cafe", "sub_category": "dessert", "sigungu": "성동구",
          "tags_any": ["뷰맛집", "기념일", "웨이팅있음"]}]}},
    {"id": "L4_naver_blog_multi", "input": "https://m.blog.naver.com/fakeblog/220000000002",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "반지공방 은솔", "primary_category": "activity", "sub_category": "workshop", "sigungu": "중구",
          "tags_any": ["예약필수"]},
         {"name": "갤러리 빛결", "primary_category": "culture", "sub_category": "exhibition", "sigungu": "종로구",
          "tags_any": ["이색적인"]},
         {"name": "이자카야 달밤", "primary_category": "bar", "sub_category": "izakaya", "sigungu": "중구",
          "tags_any": ["레트로", "웨이팅있음", "늦게까지영업"]}]}},
    {"id": "L5_naver_short_place", "input": "https://naver.me/FAKE05",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "바다정원 글램핑", "primary_category": "stay", "sub_category": "glamping", "sigungu": "강릉시",
          "tags_any": []}]}},
    {"id": "I1_insta_cafe", "input": "eval/fixtures/images/i1_insta_cafe.png",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "모모 베이커리", "primary_category": "cafe", "sub_category": "bakery", "sigungu": "마포구",
          "tags_any": ["웨이팅있음", "반려동물동반"]}]}},
    {"id": "I2_naver_place_capture", "input": "eval/fixtures/images/i2_naver_place.png",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "이자카야 달밤", "primary_category": "bar", "sub_category": "izakaya", "sigungu": "중구",
          "tags_any": []}]}},
    {"id": "I3_story_popup", "input": "eval/fixtures/images/i3_story_popup.png",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "포근곰 팝업스토어", "primary_category": "culture", "sub_category": "popup", "sigungu": "성동구",
          "tags_any": ["예약필수"]}]}},
    {"id": "I4_escape_room", "input": "eval/fixtures/images/i4_escape.png",
     "expected": {"status_in": ["complete", "needs_review"], "places": [
         {"name": "미스터리룸", "primary_category": "activity", "sub_category": "escape_room", "sigungu": "마포구",
          "tags_any": ["첫데이트", "감성"]}]}},
    {"id": "I5_not_a_place", "input": "eval/fixtures/images/i5_selfie.png",
     "expected": {"status_in": ["needs_user_input"], "places": []}},
]


def _render_png(path: Path, text: str):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    font = None
    for cand in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/System/Library/Fonts/AppleSDGothicNeo.ttc", "C:/Windows/Fonts/malgun.ttf"]:
        if Path(cand).exists():
            font = ImageFont.truetype(cand, 30)
            break
    if font is None:
        return False
    lines = text.splitlines()
    img = Image.new("RGB", (750, 120 + 52 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 750, 70], fill="#f2f2f2")
    d.text((24, 18), "(가상 캡쳐 · 평가용)", fill="#888", font=font)
    for i, line in enumerate(lines):
        d.text((24, 96 + 52 * i), line, fill="black", font=font)
    img.save(path)
    return True


def main():
    PAGES.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    for name, html in {"ig_ok.html": IG_OK, "naver_blog_single.html": NAVER_BLOG_SINGLE,
                       "naver_blog_multi.html": NAVER_BLOG_MULTI, "naver_place.html": NAVER_PLACE}.items():
        (PAGES / name).write_text(html, encoding="utf-8")
    (PAGES / "index.json").write_text(json.dumps(PAGES_INDEX, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered = 0
    for name, text in IMAGES_TEXT.items():
        (IMAGES / (name + ".ocr.txt")).write_text(text, encoding="utf-8")
        rendered += _render_png(IMAGES / name, text)
        if not (IMAGES / name).exists():  # 폰트가 없으면 빈 PNG 자리표시자
            (IMAGES / name).write_bytes(b"")
    (FIX / "geo_places.json").write_text(json.dumps(GEO_PLACES, ensure_ascii=False, indent=2), encoding="utf-8")
    with (HERE / "dataset.jsonl").open("w", encoding="utf-8") as f:
        for row in DATASET:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"fixtures ok: pages={len(PAGES_INDEX)} images={len(IMAGES_TEXT)} (png rendered {rendered}) cases={len(DATASET)}")


if __name__ == "__main__":
    main()

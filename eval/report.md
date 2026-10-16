# 평가 리포트 — `heuristic + geo=fixture + ocr=sidecar`

> 픽스처의 장소는 모두 가상입니다. 실제 LLM 평가 시 결과는 모델에 따라 달라집니다.

| 필드 | 정답 | 전체 | 정확도 |
|---|---|---|---|
| status | 10 | 10 | 100% |
| place_found | 10 | 10 | 100% |
| name | 10 | 10 | 100% |
| primary_category | 10 | 10 | 100% |
| sub_category | 10 | 10 | 100% |
| sigungu | 10 | 10 | 100% |
| tags_any | 8 | 8 | 100% |
| geo_matched | 10 | 10 | 100% |

## 케이스별

- ✅ **L1_instagram_ok** — status `complete`
  - 비노 루체 · bar/wine_bar · 마포구 · tags=['아늑한', '조용한', '기념일', '예약필수', '콜키지가능'] · conf=0.86 · complete
- ✅ **L2_instagram_blocked** — status `needs_user_input`
- ✅ **L3_naver_blog_single** — status `complete`
  - 카페 온담 · cafe/dessert · 성동구 · tags=['뷰맛집', '기념일', '예약필수', '웨이팅있음'] · conf=0.885 · complete
- ✅ **L4_naver_blog_multi** — status `complete`
  - 반지공방 은솔 · activity/workshop · 중구 · tags=['예약필수'] · conf=0.875 · complete
  - 갤러리 빛결 · culture/exhibition · 종로구 · tags=['이색적인'] · conf=0.875 · complete
  - 이자카야 달밤 · bar/izakaya · 중구 · tags=['감성', '레트로', '웨이팅있음', '늦게까지영업'] · conf=0.875 · complete
- ✅ **L5_naver_short_place** — status `complete`
  - 바다정원 글램핑 · stay/glamping · 강릉시 · tags=[] · conf=0.9 · complete
- ✅ **I1_insta_cafe** — status `complete`
  - 모모 베이커리 연남 · cafe/bakery · 마포구 · tags=['실외', '반려동물동반', '웨이팅있음'] · conf=0.845 · complete
- ✅ **I2_naver_place_capture** — status `complete`
  - 이자카야 달밤 · bar/izakaya · 중구 · tags=[] · conf=0.9 · complete
- ✅ **I3_story_popup** — status `complete`
  - 포근곰 팝업스토어 · culture/popup · 성동구 · tags=['예약필수'] · conf=0.825 · complete
- ✅ **I4_escape_room** — status `complete`
  - 미스터리룸 · activity/escape_room · 마포구 · tags=['감성', '첫데이트'] · conf=0.86 · complete
- ✅ **I5_not_a_place** — status `needs_user_input`

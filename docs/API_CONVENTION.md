# OneClickMeet V3 — 백엔드·프론트엔드 연결 API 및 코드 컨벤션

> 기준: Figma `와이어프레임(mid-fi)` › `V3 - 재원` 확정 IA
> 구현 위치: `placeflow/v3/` (Python 3.10+, pydantic v2)
> 실험 서버: `python -m placeflow serve`. V3 화면은 `/`, 이전 v0.2 화면은 `/legacy`에서 열림
> 이 문서는 **계약(contract)** 이다. 앱 백엔드를 다른 언어로 새로 만들 때도 요청·응답 모양과 에러 코드는 그대로 지킨다.

---

## 0. 한눈에 보기

```
[프론트(앱)] ──HTTP JSON──▶ [백엔드 API]  ──import──▶  placeflow.v3.service.OneClickMeetService
                                                         ├─ save_flow   (링크·스크린샷·검색 → 후보)
                                                         ├─ recommend   (도보 코스 추천)
                                                         ├─ domain      (코스 편집·항목·검증 순수 함수)
                                                         ├─ search      (네이버 지역검색 / 데모)
                                                         └─ repo        (저장소 인터페이스, 실험용 JsonRepo)
```

| 연결 방식 | 언제 쓰나 |
|---|---|
| **A. Python 백엔드에서 직접 import** | FastAPI·Django 같은 Python 서버. `OneClickMeetService`를 만들고, 엔드포인트마다 메서드 하나를 호출한다. 저장소만 DB 구현체로 바꾸면 된다(§7). |
| **B. 이 문서의 REST 계약대로 다른 언어로 재구현** | Spring·Node 서버. 추천·후보 로직은 Python 서비스(사이드카)로 띄우고, 나머지 CRUD는 직접 구현한다. |
| **C. 실험 서버 그대로 사용** | 프론트 개발 초기의 목업 서버. `/api/v3/*`가 이 문서와 똑같이 동작한다. |

---

## 1. 공통 규칙

### 1.1 URL · 메서드

- 접두사는 `/api/v3`.
- 리소스 이름은 **복수형 kebab-case**: `/saved-places`, `/courses`, `/recommendations`.
- 메서드
  - 조회: `GET`
  - 생성이나 "계산 요청"(추천, 후보 찾기): `POST`
  - 전체 교체·수정: `PUT`
  - 삭제: `DELETE`
- 경로 파라미터는 ID: `/courses/{course_id}`, `/places/{place_id}`. 쿼리는 필터: `?scope=personal|couple`.

### 1.2 응답 봉투 (Envelope)

모든 응답은 아래 두 모양 중 하나다.

```json
{ "ok": true,  "data": { ... } }
{ "ok": false, "error": { "code": "version_conflict", "message": "다른 사람이 먼저 코스를 수정했어요. ..." } }
```

- **HTTP 상태코드와 `error.code`를 함께 본다.** 화면 분기는 `error.code`로 한다.
- `message`는 사용자에게 그대로 보여줘도 되는 한국어 문장이다.
- **정상 흐름의 분기는 실패가 아니다.**
  - 예: "추천할 후보가 부족함", "스크린샷에서 장소를 못 찾음".
  - 이런 경우는 `200 OK` + `data.status`로 내려준다(§3).
  - 프론트는 `data.status`를 보고 각 실패 화면으로 보낸다.

### 1.3 에러 코드 → HTTP

| code | HTTP | 뜻 / 프론트 처리 |
|---|---|---|
| `invalid_input` | 400 | 필수 값 누락, 형식 오류. 입력 화면에 메시지 표시 |
| `invalid_op` / `invalid_order` | 400 | 코스 편집 요청이 잘못됨 (순서 목록 불일치 등) |
| `forbidden` | 403 | 남의 코스 수정 시도 |
| `place_not_found` / `course_not_found` / `stop_not_found` / `item_not_found` / `not_saved` / `not_found` | 404 | 대상 없음. 목록을 새로고침 |
| `version_conflict` | 409 | 공동 코스 동시 수정. "새로 불러오기" 안내 |
| `too_few_stops` / `too_many_stops` / `duplicate_place` / `orphan_item` | 422 | 코스 저장 규칙 위반(3~5곳, 중복, 고아 항목) |
| `external_api_failed` | 502 | 외부 검색 API 실패 (검색 이외 경로에서 발생한 경우) |
| `extractor_unavailable` | 503 | 링크·스크린샷 추출기 설정 오류 |
| `internal` | 500 | 서버 버그 (실험 서버는 `detail`에 traceback 포함) |
| `network` | — | **프론트 전용.** `fetch` 자체가 실패함 → 네트워크 오류 화면 |

### 1.4 데이터 표기

| 항목 | 규칙 |
|---|---|
| JSON 키 | `snake_case` (`place_id`, `share_with_couple`) |
| ID | 접두사 + 무작위: `sp_`(저장), `co_`(코스), `st_`(코스 안 장소), `it_`(항목). 장소는 `nv_` + sha1(이름\|도로명주소) 16자 |
| 시간 | ISO-8601 UTC 문자열 `2026-10-16T05:12:00+00:00` |
| 금액 | **정수 원(KRW), 2인 합계.** 0 ≤ amount ≤ 10,000,000 |
| 좌표 | WGS84 `lat`, `lng` (float) |
| 거리·시간 | 도보 분은 정수(올림). 반경은 m |
| 사용자 | 실험 서버는 `X-User-Id` 헤더를 쓴다(기본 `me`). **실서비스는 인증 토큰에서 user_id를 꺼내고, 이 헤더는 받지 않는다.** |
| 빈 값 | 없으면 `null`. 빈 배열은 `[]` (키를 생략하지 않음) |

### 1.5 프론트 호출 규칙

```js
// 공통 호출기 — 실험 화면(placeflow/web/index.html)의 api() 와 같은 규칙
async function api(method, path, body) {
  let res;
  try {
    res = await fetch('/api/v3' + path, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch { throw new ApiError('network', '서버에 연결하지 못했어요.'); }
  const j = await res.json();
  if (!j.ok) throw new ApiError(j.error.code, j.error.message, res.status);
  return j.data;            // 화면 분기는 data.status 로
}
```

1. **POST·PUT 본문은 항상 JSON**(`Content-Type: application/json`). 이미지도 base64로 JSON에 넣는다(§4.2).
2. **서버가 계산한 값을 그대로 쓴다.** 프론트에서 금액 합계, 도보 시간, 저장 가능 여부를 다시 계산하지 않는다. 코스를 편집할 때마다 `/courses/ops`를 호출하고, 응답의 `summary`를 그린다.
3. **드래프트는 프론트가 들고 있다.** 추천에서 고른 코스는 `POST /courses`를 하기 전까지 서버에 저장되지 않는다. 화면을 나갈 때 `dirty`면 "저장하지 않고 나갈까요?"를 띄운다.
4. **코스를 수정해서 저장할 때는 항상 `expected_version`을 보낸다.** 409를 받으면 덮어쓰지 말고 다시 불러오게 한다.
5. **"다시 추천받기"를 할 때는 지금까지 보여준 모든 `signature`를 `exclude_signatures`에 누적해서 보낸다.**
6. 로딩 단계 문구 3개(근처 후보 찾는 중 → 도보 거리 확인 중 → 코스 구성 중)는 응답의 `steps`와 같다. 요청 중에는 프론트가 시간에 맞춰 순서대로 보여준다.

---

## 2. 데이터 모델

> 정의 원본: `placeflow/v3/domain.py`, `recommend.py`, `save_flow.py`. 아래는 JSON 모양이다.

### Place — 장소 원본 (보관함 저장 여부와는 별개)
```json
{
  "place_id": "nv_3f2a9c0d1e4b5a6c", "name": "연남 파스타집", "branch": null,
  "category": "restaurant", "sub_category": "western", "category_label": "맛집",
  "area_label": "연남동", "road_address": "서울 마포구 ...", "jibun_address": null,
  "lat": 37.5626, "lng": 126.9255, "phone": null, "map_url": null,
  "provider": "naver_local",
  "opening_hours": null,
  "subtitle": "맛집 · 연남동",
  "hours_notice": "방문 전에 운영시간을 확인해주세요."
}
```
- `subtitle`과 `hours_notice`는 **응답에만 붙는 표시용 필드**다. 요청으로 보낼 때는 있어도 무시된다.
- `category`는 `restaurant | cafe | bar | culture | activity | nature | shopping | stay | other` 중 하나다.
- `opening_hours`가 없으면 `hours_notice`는 고정 문구다(V3: "운영시간을 확인해주세요").
- `provider`는 `naver_local | demo | link` 중 하나다.

### SavedPlace — 하트(보관함 저장)
```json
{ "saved_id": "sp_...", "owner_id": "me", "place_id": "nv_...", "origin": "link",
  "source_url": "https://www.instagram.com/reel/...", "shared_with_couple": false, "saved_at": "..." }
```
`origin`은 `link | screenshot | search | recommendation | demo` 중 하나다.

### PrivateMemo — 내 메모 (작성자 본인만 조회)
`{ "owner_id", "target_type": "place|course", "target_id", "text" (≤1000), "updated_at" }`

### Anchor — 추천 기준
```json
{ "type": "place",  "place_id": "nv_..." }
{ "type": "region", "region_id": "yeonnam" }
```

### Course · CourseStop · CourseItem
```json
{
  "course_id": "co_...", "owner_id": "me", "scope": "personal", "couple_id": null,
  "title": "연남동 데이트 코스", "anchor": { "type": "place", "place_id": "nv_..." },
  "stops": [ { "stop_id": "st_...", "place": { /* Place */ }, "is_anchor": true, "external": false } ],
  "items": [ { "item_id": "it_...", "stop_id": "st_...", "name": "파스타 2개", "amount": 30000,
               "checked": true, "updated_by": "me", "updated_at": "..." } ],
  "version": 1, "created_at": "...", "updated_at": "..."
}
```
- `external`이 true면 추천 시점에 보관함에 없던 장소다. 화면에 **외부 추천** 배지를 붙인다.
- `items`는 코스마다 따로 관리되고, `stop_id`로 장소에 묶인다.

### CourseSummary — 서버가 계산하는 요약
```json
{
  "stops": [ { "stop_id": "st_..", "order": 1, "name": "..", "is_anchor": true, "external": false,
               "walk_from_prev_min": null, "item_count": 1, "checked_subtotal": 30000, "has_checked": true } ],
  "confirmed_total": 30000,
  "unchecked_stop_count": 3,
  "total_walk_min": 18,
  "long_legs": [],
  "can_save": true,
  "save_errors": []
}
```
- `confirmed_total`: 확인된 금액. 체크한 항목만 더한다.
- `unchecked_stop_count`: "체크된 항목 없음 N곳".
- `long_legs`: 도보 10분을 넘는 구간의 도착 순번 (편집 후 경고용).

### RecommendResult
```json
{
  "status": "ok",
  "region": { "region_id": "yeonnam", "name": "연남" },
  "candidates_count": 24,
  "steps": [ { "key": "candidates", "label": "근처 후보 찾는 중", "done": true },
             { "key": "walking",    "label": "도보 거리 확인 중", "done": true },
             { "key": "compose",    "label": "코스 구성 중",     "done": true } ],
  "courses": [ {
      "signature": "nv_a|nv_b|nv_c|nv_d",
      "stops": [ { "order": 1, "place": { /* Place */ }, "source": "external", "is_anchor": false,
                   "external": true, "walk_from_prev_min": null },
                 { "order": 2, "place": { }, "source": "mine", "is_anchor": true, "external": false,
                   "walk_from_prev_min": 3 } ],
      "total_walk_min": 15, "saved_count": 3, "external_count": 1, "score": 27.2,
      "reasons": ["저장한 장소 3곳 포함", "맛집 · 카페·디저트 · 술집·바", "장소 사이 최대 도보 7분"] } ],
  "message": null
}
```
`source`는 `mine | couple | external` 중 하나다.

### ResolveResult — 장소 후보 확인
```json
{
  "status": "candidates",
  "candidates": [ { "place": { /* Place + subtitle */ }, "match_score": 0.93,
                    "already_saved": false, "from_text": "아루" } ],
  "suggested_query": "아루",
  "extracted": [ { "name": "아루", "branch": null, "address_hint": "서울 마포구 ...", "category": "맛집" } ],
  "message": null
}
```

---

## 3. 상태값 (`data.status`) → 화면

### 3.1 장소 후보 (`POST /places/resolve`, `GET /places/search`)

| status | 화면 (Figma) | 프론트 동작 |
|---|---|---|
| `candidates` | 후보 확인 "이 장소가 맞나요?" | 라디오 목록. 첫 번째 후보를 기본 선택 → `POST /saved-places` |
| `no_match` | 직접 검색 | 검색창에 `suggested_query`를 미리 채움 |
| `recognition_failed` | 스크린샷 인식 실패 | [직접 검색] / [다른 이미지 선택] |
| `link_unreadable` | 링크 읽기 실패 (인스타 로그인 벽 등) | [직접 검색] / [스크린샷으로 올리기] |
| `search_failed` | 외부 검색 실패 | [다시 시도] / [직접 검색] |

### 3.2 코스 추천 (`POST /recommendations`)

| status | 화면 | 프론트 동작 |
|---|---|---|
| `ok` | 코스 1/2/3 | 탭 3개, 지도, 목록, [편집] [이 코스 선택] [다시 추천받기] |
| `unsupported_region` | 지원하지 않는 지역 | [다른 기준 선택]. 지원 지역 안내 문구는 `message` |
| `not_enough_candidates` | 후보 부족 | [다른 기준 선택] [장소 더 저장하기]. **지역을 자동으로 넓히지 않음** |
| `external_api_failed` | 외부 API 실패 | [다시 시도] [다른 기준 선택]. 이번에는 코스를 만들지 않음 |
| `no_result` | 결과 없음 (다시 추천해도 새 코스 없음) | [다른 기준 선택] |
| `anchor_not_found` | 기준 장소 없음 | 보관함에서 다시 선택 |

---

## 4. 엔드포인트

> 표의 "서비스 메서드"는 `OneClickMeetService`의 메서드다. Python 백엔드는 이 메서드를 그대로 호출하면 된다.

### 4.1 목록

| # | 메서드 · 경로 | 화면 (Figma V3) | 서비스 메서드 |
|---|---|---|---|
| 1 | `GET /home` | 홈 | `home(uid)` |
| 2 | `GET /regions` | 기준 선택 › 지역 | `regions(uid)` |
| 3 | `POST /places/resolve` | 장소 추가 → 인식 중 → 후보 확인 / 실패 | `resolve_place(uid, kind, ...)` |
| 4 | `GET /places/search?q=` | 직접 검색 | `resolve_place(uid, "search", query=q)` |
| 5 | `GET /places/{place_id}` | 장소 상세 | `place_detail(uid, place_id)` |
| 6 | `POST /saved-places` | 후보 확인 › 개인 보관함에 저장 / 하트 ON | `save_place(uid, place, origin, source_url, share_with_couple)` |
| 7 | `DELETE /saved-places/{place_id}` | 하트 OFF | `unsave_place(uid, place_id)` |
| 8 | `GET /saved-places?scope=personal\|couple` | 보관함 (목록·지도) | `list_saved(uid, scope)` |
| 9 | `PUT /memos` | 장소·코스 상세 › 내 메모 | `set_memo(uid, target_type, target_id, text)` |
| 10 | `POST /recommendations/conditions` | 추천 조건 확인 | `recommend_conditions(uid, anchor)` |
| 11 | `POST /recommendations` | 로딩 → 코스 1/2/3 / 실패 화면 | `recommend(uid, anchor, exclude_signatures)` |
| 12 | `POST /recommendations/replacements` | 코스 편집 › 교체 시트 | `replacement_candidates(uid, place_ids, index)` |
| 13 | `POST /courses/draft` | 이 코스 선택 → 코스 상세(저장 전) | `draft_from_recommendation(uid, recommended, anchor)` |
| 14 | `POST /courses/ops` | 코스 상세·편집의 모든 수정 | `apply_op(uid, course, op)` |
| 15 | `POST /courses` | 코스 저장 (처음) | `save_course(uid, course, None, memo)` |
| 16 | `PUT /courses/{course_id}` | 변경 사항 저장 | `save_course(uid, course, expected_version, memo)` |
| 17 | `GET /courses?scope=` | 코스 탭 목록 | `list_courses(uid, scope)` |
| 18 | `GET /courses/{course_id}` | 코스 상세 (저장됨) | `get_course(uid, course_id)` |
| 19 | `DELETE /courses/{course_id}` | 코스 삭제 | `delete_course(uid, course_id)` |
| — | `GET·PUT /settings`, `POST /dev/seed`, `POST /dev/reset` | 마이 (실험 전용) | **실서비스에는 만들지 않음** |

### 4.2 요청·응답 예시

#### ③ 장소 후보 찾기 — `POST /places/resolve`
```jsonc
// 링크
{ "type": "link", "url": "https://www.instagram.com/reel/xxx", "note": "(선택) 캡션 붙여넣기" }
// 스크린샷 (최대 5장, png/jpg/jpeg/webp/gif, dataURL 또는 base64)
{ "type": "screenshot", "images": [ { "name": "a.png", "b64": "data:image/png;base64,iVBOR..." } ] }
// 텍스트(캡션만)
{ "type": "text", "note": "📍연남 보드게임 카페 서울 마포구 연남동" }
// 직접 검색 (GET /places/search 와 같음)
{ "type": "search", "query": "연남 카페" }
```
- 응답: `ResolveResult` (§2).
- **이 단계에서는 저장하지 않는다.** 저장은 ⑥에서 한다.
- 링크는 robots.txt를 지키고 호스트마다 1초 간격으로 읽는다. 인스타처럼 로그인 벽이 있으면 `link_unreadable`이 나온다.

#### ⑥ 보관함에 저장 — `POST /saved-places`
```json
{ "place": { "place_id": "nv_...", "name": "...", "lat": 37.56, "lng": 126.92, "...": "..." },
  "origin": "link", "source_url": "https://www.instagram.com/reel/xxx", "share_with_couple": false }
```
- 응답: `{ "saved": SavedPlace, "place": Place }`.
- 같은 장소를 다시 저장해도 하나만 유지된다(**멱등**).
- 커플 연결이 없으면 `share_with_couple`은 무시된다.

#### ⑤ 장소 상세 — `GET /places/{place_id}`
```json
{ "place": { "...": "...", "hours_notice": "월-일 11:30-21:30 · 브레이크 15:00-17:00" },
  "hearted": true, "source_url": "https://...", "shared_with_couple": false,
  "my_memo": "웨이팅 길면 카페부터",
  "nearby": [ { "...": "Place", "source": "external" } ] }
```
`nearby`는 걸어서 10분 이내의 놀거리·카페 최대 3곳이다. 저장한 장소를 먼저 보여준다.

#### ⑨ 내 메모 — `PUT /memos`
`{ "target_type": "place", "target_id": "nv_...", "text": "..." }`. 빈 문자열을 보내면 삭제된다. 메모는 작성자만 조회할 수 있다(커플 상대도 볼 수 없음).

#### ⑪ 코스 추천 — `POST /recommendations`
```json
{ "anchor": { "type": "place", "place_id": "nv_..." }, "exclude_signatures": [] }
```
- 응답: `RecommendResult`.
- 다시 추천받을 때는 앞에서 받은 `courses[].signature`를 **모두** 누적해서 보낸다.

#### ⑫ 교체 후보 — `POST /recommendations/replacements`
```json
{ "place_ids": ["nv_a", "nv_b", "nv_c", "nv_d"], "index": 1 }
```
- 응답: `{ "candidates": [ Place + "source" ] }`, 최대 8곳이다.
- 앞·뒤 장소 **양쪽에서 모두** 도보 10분 이내인 곳만 고른다. 저장한 장소가 먼저 나온다.

#### ⑬ 드래프트 만들기 — `POST /courses/draft`
```json
{ "recommended": { /* RecommendedCourse 그대로 */ }, "anchor": { "type": "place", "place_id": "nv_..." } }
```
응답: `{ "course": Course(version 0), "summary": CourseSummary, "my_memo": "" }`. 아직 저장된 상태가 아니다.

#### ⑭ 코스 편집 1건 — `POST /courses/ops`
```jsonc
{ "course": { /* 현재 드래프트 Course */ }, "op": { "type": "add_item", "stop_id": "st_..", "name": "파스타 2개", "amount": 30000 } }
```
| op.type | 필드 | 규칙 |
|---|---|---|
| `reorder` | `stop_ids` (전체, 새 순서) | 항목 **유지** |
| `replace` | `stop_id`, `place` | 그 장소의 항목 **삭제**. 중복 장소는 `duplicate_place` |
| `remove_stop` | `stop_id` | 그 장소의 항목 **삭제** |
| `add_stop` | `place`, `index?` (없으면 맨 뒤) | 5곳 초과면 `too_many_stops` |
| `add_item` | `stop_id`, `name`(1~40자), `amount`, `checked?`(기본 true) | 금액은 2인 합계 |
| `update_item` | `item_id`, `name?`, `amount?`, `checked?` | |
| `remove_item` | `item_id` | |

- 응답: `{ "course", "summary" }`.
- 서버는 저장하지 않는다. 프론트는 받은 `course`로 드래프트를 바꾼다.
- 편집 중에는 3곳 미만이 되어도 되지만, 그러면 `summary.can_save=false`가 된다.

#### ⑮⑯ 코스 저장
```jsonc
POST /courses                 { "course": { ... }, "memo": "(선택) 내 메모" }
PUT  /courses/{course_id}     { "course": { ... }, "expected_version": 3, "memo": "..." }
```
- 응답: `{ "course": Course(version+1), "summary", "my_memo" }`.
- 3~5곳, 중복, 고아 항목을 검사하고, 어기면 422를 돌려준다.
- `expected_version`이 다르면 409를 돌려준다.
- **코스를 저장해도 그 안의 장소가 보관함에 자동으로 담기지 않는다.**
- 프론트 저장 버튼의 상태는 `idle` → `saving` → `done`이고, 실패하면 `failed`가 되어 [다시 시도]를 보여준다.

---

## 5. 비즈니스 규칙 (V3 확정)

| 영역 | 규칙 | 코드 위치 |
|---|---|---|
| 이동 | 도보만. 도보 분 = 직선거리 × 1.3 ÷ 4.5km/h, 올림 | `walking.walk_minutes` |
| 범위 | 기준 장소 반경 1,000m (`ANCHOR_RADIUS_M`), 장소 사이 도보 10분 이하 (`MAX_LEG_MIN`) | `walking.py` |
| 코스 | 3~5곳. 기준 장소는 반드시 포함하고 **위치는 상관없음**(처음·중간·끝) | `recommend._search_paths` |
| 개수 | 최대 3개를 서로 다르게 고름(겹치는 장소 1곳 → 2곳 순으로 완화) | `recommend.recommend` |
| 다시 추천 | `exclude_signatures`에 있는 코스는 다시 내지 않음 | `recommend.recommend` |
| 지역 | 지원 지역 6곳(연남·서촌·혜화·잠실·성신여대역·한성대입구역). **자동으로 넓히지 않음** | `regions.py` |
| 후보 | 내 보관함 + 공동 보관함(저장 가산점) + 외부 추천(네이버 지역검색 "지역명 + 업종") 최대 30곳 | `recommend.gather_candidates` |
| 운영시간 | 데이터가 없으면 "방문 전에 운영시간을 확인해주세요." (추천 필터에는 쓰지 않음) | `domain.HOURS_NOTICE` |
| 항목 | 코스마다 따로 관리. 금액은 2인 합계. 체크한 것만 확인된 금액에 더함. 순서를 바꾸면 유지, 교체·삭제하면 삭제 | `domain.py` |
| 하트 | 하트 = SavedPlace가 있는지 여부. 하트를 꺼도 코스 안 장소는 그대로 | `repo.py` |
| 메모 | 작성자 본인만 조회 | `repo.get_memo` |
| 동시 수정 | 저장할 때마다 `version`+1. 다르면 409 | `repo.save_course` |
| 개인정보 | 추출 단계에서 개인 전화·이메일·@계정·주민번호 형태를 저장하지 않음 | `placeflow/normalize.py` |

---

## 6. Python 함수 레퍼런스 (백엔드 import용)

### 6.1 조립

```python
from placeflow.v3.repo import JsonRepo                  # 실서비스는 같은 메서드의 DB 구현체로 교체
from placeflow.v3.search import get_search_provider     # "auto" | "naver" | "demo" | "demo_fail"
from placeflow.v3.service import OneClickMeetService
from placeflow.cli import build_pipeline                # 링크·스크린샷 추출

svc = OneClickMeetService(
    repo=JsonRepo("data/v3.json"),
    search=get_search_provider("auto"),                  # NAVER_CLIENT_ID/SECRET 이 있으면 네이버
    pipeline_factory=lambda: build_pipeline("heuristic", None, "none", "auto"),  # (llm, model, geo, ocr)
)

# FastAPI 예시
@app.post("/api/v3/recommendations")
def recommend(body: dict, user=Depends(current_user)):
    try:
        return {"ok": True, "data": svc.recommend(user.id, body["anchor"], body.get("exclude_signatures", []))}
    except DomainError as e:
        raise HTTPException(HTTP_OF.get(e.code, 422), {"ok": False, "error": {"code": e.code, "message": e.message}})
```
에러 매핑 표 `HTTP_OF`는 `placeflow/v3/api.py`에 있다.

### 6.2 서비스 (`placeflow/v3/service.py`) — 모든 반환값은 JSON 직렬화 가능한 dict

```python
class OneClickMeetService:
    def home(user_id) -> dict
    def regions(user_id) -> list[dict]
    def resolve_place(user_id, kind, *, url=None, text=None, image_paths=None, query=None) -> dict  # ResolveResult
    def save_place(user_id, place: dict, origin="search", source_url=None, share_with_couple=False) -> dict
    def unsave_place(user_id, place_id) -> dict
    def list_saved(user_id, scope="personal") -> dict
    def place_detail(user_id, place_id) -> dict
    def set_memo(user_id, target_type, target_id, text) -> dict
    def recommend_conditions(user_id, anchor: dict) -> dict
    def recommend(user_id, anchor: dict, exclude_signatures=None) -> dict                            # RecommendResult
    def replacement_candidates(user_id, place_ids: list[str], index: int) -> dict
    def draft_from_recommendation(user_id, recommended: dict, anchor: dict) -> dict
    def apply_op(user_id, course: dict, op: dict) -> dict
    def save_course(user_id, course: dict, expected_version=None, memo=None) -> dict
    def list_courses(user_id, scope="personal") -> dict
    def get_course(user_id, course_id) -> dict
    def delete_course(user_id, course_id) -> dict
    def seed_demo(user_id, region_id="yeonnam", n=4) -> dict                                        # 실험 전용
```
규칙을 어기면 `DomainError(code, message)`가 발생한다.

### 6.3 하위 모듈 (직접 써도 됨)

```python
# domain.py — 순수 함수. 입력 Course 를 바꾸지 않고 새 Course 를 반환
reorder_stops(course, stop_ids) -> Course
replace_stop(course, stop_id, place, external=False) -> Course
remove_stop(course, stop_id) -> Course
add_stop(course, place, index=None, external=False) -> Course
add_item(course, stop_id, name, amount, checked=True, by=None) -> Course
update_item(course, item_id, *, name=None, amount=None, checked=None, by=None) -> Course
remove_item(course, item_id) -> Course
validate_for_save(course) -> list[str]          # [] 이면 저장 가능
summarize(course) -> CourseSummary

# recommend.py
recommend(req: RecommendRequest, user_pool: list[tuple[Place, "mine"|"couple"]], search, anchor_place=None) -> RecommendResult
replacement_candidates(course_places: list[Place], index, user_pool, search, limit=8) -> list[Cand]
nearby_places(place, user_pool, search, limit=3) -> list[Cand]
to_course_draft(rec: RecommendedCourse, owner_id, anchor, title=None) -> Course
signature_of(place_ids) -> str

# save_flow.py
search_candidates(search, query, is_saved=lambda pid: False) -> ResolveResult
candidates_from_records(records: list[PlaceRecord], search, input_kind, is_saved=..., pipeline_message=None) -> ResolveResult
save_candidate(repo, owner_id, place, origin, source_url=None, share_with_couple=False) -> SavedPlace

# search.py
class SearchProvider(Protocol): name: str; def search(query, display=5) -> list[Place]
NaverLocalSearch(client_id=None, client_secret=None, timeout=6.0, cache_ttl=6*3600)  # 실패 시 ExternalSearchError
DemoSearch(fail=False)
make_place_id(name, road_address, jibun=None) -> str

# walking.py
distance_m(a, b) -> float;  walk_minutes(a, b) -> int;  walkable(a, b, limit=10) -> bool
```

---

## 7. 저장소 인터페이스 (DB로 바꿀 때 구현할 메서드)

`JsonRepo`는 실험용이다. 실서비스는 아래 메서드를 같은 의미로 구현한 클래스를 `OneClickMeetService(repo=...)`에 넣는다.

```python
class Repo(Protocol):
    def couple_members(user_id) -> list[str]            # 커플이면 [나, 상대], 아니면 [나]
    def couple_id_of(user_id) -> str | None
    def upsert_place(place: Place) -> Place              # 비어 있던 필드만 채움
    def get_place(place_id) -> Place | None
    def save_place(owner_id, place, origin, source_url, share_with_couple) -> SavedPlace   # 멱등
    def unsave_place(owner_id, place_id) -> bool
    def set_share(owner_id, place_id, shared) -> SavedPlace
    def list_saved(user_id, scope) -> list[tuple[SavedPlace, Place]]   # 최신순
    def is_saved(user_id, place_id) -> bool
    def recommendation_pool(user_id) -> list[tuple[Place, "mine"|"couple"]]
    def set_memo(owner_id, target_type, target_id, text) -> PrivateMemo  # 빈 text = 삭제
    def get_memo(owner_id, target_type, target_id) -> PrivateMemo | None
    def save_course(course, expected_version=None) -> Course            # version+1, 불일치 시 DomainError("version_conflict")
    def get_course(course_id) -> Course | None
    def list_courses(user_id, scope) -> list[Course]
    def delete_course(course_id) -> bool
```

권장 테이블 (RDB):

| 테이블 | 키 / 주요 컬럼 |
|---|---|
| `places` | `place_id` PK, name, category, sub_category, lat, lng, road_address, opening_hours(JSON), provider |
| `saved_places` | `saved_id` PK, **UNIQUE(owner_id, place_id)**, origin, source_url, shared_with_couple, saved_at |
| `memos` | **PK(owner_id, target_type, target_id)**, text |
| `courses` | `course_id` PK, owner_id, scope, couple_id, title, anchor(JSON), version, timestamps |
| `course_stops` | `stop_id` PK, course_id FK, ord, place_id FK, is_anchor, external |
| `course_items` | `item_id` PK, course_id FK, stop_id FK (**ON DELETE CASCADE**), name, amount, checked, updated_by |

코스를 저장할 때는 `UPDATE courses SET version=version+1 WHERE course_id=? AND version=?`를 실행한다. 바뀐 행이 0개면 409를 돌려준다.

---

## 8. 환경 변수

| 이름 | 용도 | 필수 |
|---|---|---|
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 네이버 지역검색 키. **NAVER API HUB**(네이버 클라우드 플랫폼 콘솔 › NAVER API HUB › Application › 인증 정보)에서 발급. 현재 무료 기간, 검색 API 하루 25,000건 | 실서비스 필수. 없으면 데모 데이터 사용 |
| `NAVER_SEARCH_ENDPOINT` | `hub`(기본, `naverapihub.apigw.ntruss.com/search/v1/local`, 헤더 `X-NCP-APIGW-API-KEY-ID`/`X-NCP-APIGW-API-KEY`) 또는 `legacy`(개발자센터 기존 키, 2027-06-30까지) | 선택 |
| `PLACEFLOW_V3_DB` | 실험 저장 파일 경로 (기본 `data/v3.json`) | 선택 |
| `OPENAI_API_KEY` 등 | 링크·스크린샷 정보 보강(LLM). 없어도 규칙 기반·OCR로 동작 | 선택 |
| `PLACEFLOW_LLM_MODEL` | LLM 모델 이름 | LLM을 쓸 때 |

`.env`는 커밋하지 않는다.

---

## 9. 테스트 · 확인

```bash
python3 -m pytest -q tests/test_v3.py      # V3 도메인·추천·저장 흐름·HTTP 엔드포인트 (네트워크 불필요)
python3 -m placeflow serve                 # http://127.0.0.1:8000  → 마이 › 데모 보관함 채우기
```

---

## 10. 미정(TBD) · 주의

- **네이버 지역검색 실제 호출은 키가 없는 환경에서 검증하지 못했다.** 응답 파싱(`mapx/mapy` = WGS84, ×1e7 정수면 자동 환산, `<b>` 태그 제거)은 공개 문서 기준이다. HUB 응답의 `telephone`은 항상 빈 값이다. 키를 넣은 뒤 마이 › 검색 "네이버"로 확인한다.
- 지원 지역 6곳의 중심 좌표와 반경(`regions.py`)은 **근사값**이다. 기획에서 확정한 경계로 교체해야 한다.
- 네이버 결과에는 고유 ID가 없어서 `place_id`를 이름과 주소의 해시로 만든다. 가게가 이전하거나 이름을 바꾸면 다른 장소로 잡힌다.
- 커플 연결(초대·수락) API는 이 범위 밖이다. 저장소에는 `couples` 최소 구조만 있다.
- 실험 서버의 `X-User-Id`, `/settings`, `/dev/*`는 실서비스에 만들지 않는다.

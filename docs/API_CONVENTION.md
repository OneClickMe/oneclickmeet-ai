# OneClickMeet AI 워크플로우 v1.1 — AI 연결 API 및 코드 컨벤션

> **범위:** 이 문서는 **AI 기능만** 다룬다.
> - 장소 인식: 링크·스크린샷·캡션에서 장소를 추출하고, 네이버 지역검색 후보와 맞춘다.
> - 코스 추천: 도보 코스 추천, 교체 후보, 주변 놀거리.
>
> 회원·보관함(하트)·메모·코스 저장/편집·커플 같은 **일반 CRUD는 백엔드 소관**이라 이 문서에서 다루지 않는다.
>
> - 기준: Figma `와이어프레임(mid-fi) › V3 - 재원` 확정 IA. "V3"는 와이어프레임 버전이고, 워크플로우 버전은 v1.1이다.
> - 구현: AI 로직 `placeflow/v3/` · AI 서버(FastAPI) `placeflow/ai_api/` (Python 3.10+, pydantic v2)
> - 실행: `python -m placeflow api --port 8001` → Swagger `http://127.0.0.1:8001/docs`, 명세 파일 `docs/openapi.json`
> - 접두사 `/ai/v1`. **상태 없음** — AI 서버는 사용자 데이터를 저장하지 않는다.

---

## 0. 한눈에 보기

```
[앱] ──▶ [백엔드] ── 사용자·보관함·코스 DB
              │
              └──HTTP──▶ [AI 서버 FastAPI /ai/v1]  placeflow.ai_api → placeflow.v3
                                 ├─ 장소 인식   pipeline(크롤링·OCR·추출) → save_flow(후보 매칭)
                                 ├─ 코스 추천   recommend(후보 수집 → 도보 그래프 → 빔 탐색)
                                 └─ 장소 검색   search(네이버 지역검색 API HUB / 데모)
```

**역할 분리**
- **백엔드**: 사용자, 저장한 장소(보관함), 코스를 DB에 보관한다. AI를 호출할 때 필요한 데이터를 요청에 담아 보낸다. 예: 사용자가 저장한 장소 목록.
- **AI**: 받은 입력으로 계산만 하고 결과를 돌려준다. **사용자 데이터를 저장하지 않는다.**
- AI가 돌려준 `Place`는 백엔드가 `place_id`를 키로 저장한다. 그 뒤 추천을 요청할 때 그대로 다시 보낸다.

**연결 방법 (백엔드도 Python)**

| 방법 | 언제 | 방법 |
|---|---|---|
| **A. HTTP 호출 (권장)** | 백엔드와 AI 서버를 따로 배포할 때. OCR·크롤링 부하를 백엔드와 분리할 수 있음 | §4의 `/ai/v1/*` 호출 |
| **B. 함수 직접 import** | 한 프로세스에서 같이 돌릴 때(초기 개발) | §6의 함수 호출. 같은 결과 모델(pydantic)을 그대로 받음 |

---

## 1. 공통 규칙

### 1.1 응답 봉투 (Envelope)
```json
{ "ok": true,  "data": { ... } }
{ "ok": false, "error": { "code": "invalid_input", "message": "링크나 공유 문구를 붙여넣어 주세요." } }
```
- `message`는 사용자에게 그대로 보여줘도 되는 한국어 문장이다.
- **정상 흐름의 분기는 실패가 아니다.**
  - 예: 후보 없음, 스크린샷 인식 실패, 추천 후보 부족.
  - 이런 경우는 `200 OK` + `data.status`로 내려준다(§3).

### 1.2 에러 코드 → HTTP

| code | HTTP | 뜻 |
|---|---|---|
| `invalid_input` | 400 | 필수 값 누락, 형식 오류 (이미지 형식, 6장 이상, 장당 10MB 초과, http 링크 아님, 요청 모델 검증 실패 등) |
| `unauthorized` | 401 | `AI_SERVICE_KEY`를 설정했는데 `X-AI-Key` 헤더가 없거나 틀림 |
| `place_not_found` | 404 | 기준 장소·교체 대상 장소 정보가 없음 |
| `external_api_failed` | 502 | 네이버 지역검색 실패 (추천에서는 `data.status`로 내려가고, 그 밖의 경로에서만 에러로 올라옴) |
| `extractor_unavailable` | 503 | 추출기 설정 오류 (LLM 키 없음, 서버에 OCR(tesseract+kor) 없음 → 스크린샷 처리 불가) |
| `internal` | 500 | 서버 버그 |

### 1.3 데이터 표기

| 항목 | 규칙 |
|---|---|
| JSON 키 | `snake_case` |
| 장소 ID | `nv_` + sha1(공백 뺀 이름 \| 도로명주소) 앞 16자. 네이버 지역검색 결과에 고유 ID가 없어서 만든다 |
| 좌표 | WGS84 `lat`, `lng` (float) |
| 도보 시간 | 정수 분(올림). 반경은 m |
| 빈 값 | 없으면 `null`. 빈 배열은 `[]` (키를 생략하지 않음) |

---

## 2. 데이터 모델

> 정의 원본: `placeflow/v3/domain.py`(Place, Anchor), `save_flow.py`, `recommend.py`

### Place — AI가 돌려주는 장소
```json
{
  "place_id": "nv_3f2a9c0d1e4b5a6c", "name": "오지다", "branch": null,
  "category": "restaurant", "sub_category": "japanese", "category_label": "맛집",
  "area_label": "방이동", "road_address": "서울특별시 송파구 백제고분로48길 24", "jibun_address": null,
  "lat": 37.5131, "lng": 127.1123, "phone": null, "map_url": null,
  "provider": "naver_local", "opening_hours": null,
  "subtitle": "맛집 · 방이동",
  "hours_notice": "방문 전에 운영시간을 확인해주세요."
}
```
- `category`는 `restaurant | cafe | bar | culture | activity | nature | shopping | stay | other` 중 하나다. 소분류 전체는 `schema/taxonomy.json`에 있다.
- `subtitle`과 `hours_notice`는 화면 표시용이라 응답에만 붙는다. 요청에 들어 있어도 무시한다.
- `provider`는 `naver_local | link | demo` 중 하나다.
- `phone`: NAVER API HUB 응답에서는 항상 비어 있다.

### Anchor — 추천 기준
```json
{ "type": "place",  "place_id": "nv_..." }
{ "type": "region", "region_id": "jamsil" }
```
지원 지역(`region_id`): `yeonnam`(연남) · `seochon`(서촌) · `hyehwa`(혜화) · `jamsil`(잠실) · `sungshin`(성신여대역) · `hansung`(한성대입구역)

### ResolveResult — 장소 인식 결과
링크·스크린샷 결과는 **링크에 나온 장소 1곳 = `groups[]` 1개**로 내려온다(릴스 '맛집 4곳' 대응). 직접 검색 결과는 `groups`가 비어 있고 `candidates`만 있다.
```json
{
  "status": "candidates",
  "groups": [
    { "extracted": { "order": 1, "name": "오지다", "branch": null,
                     "address_hint": "서울 송파구 백제고분로48길 24", "category": "맛집" },
      "status": "matched",
      "best":   { "place": { /* Place */ }, "match_score": 1.0, "match_type": "exact",
                  "reasons": ["주소 일치", "이름 일치"], "already_saved": false, "from_text": "오지다" },
      "others": [ { "place": { "name": "회포차오지다", "...": "..." }, "match_score": 0.5, "match_type": "similar",
                    "reasons": ["이름 일부만 같아요", "주소 다름"], "already_saved": false, "from_text": "오지다" } ] }
  ],
  "candidates": [ /* 모든 묶음의 best → others 순서로 한 줄 */ ],
  "suggested_query": "오지다",
  "extracted": [ /* groups[].extracted 와 같음 */ ],
  "message": null
}
```

| 필드 | 값 | 화면 처리 |
|---|---|---|
| `groups[].status` | `matched` · `similar_only` · `not_found` · `search_failed` | `not_found`·`search_failed`는 "찾지 못했어요 · 직접 검색"(검색창에 `extracted.name`) |
| `best` | `match_type="exact"`인 1순위 (없으면 `null`) | **기본 체크** |
| `others` | 최대 2~3개, 모두 `match_type="similar"` | 접어서 "다른 후보 N곳". **기본 체크하지 않음** |
| `reasons` | 일치: `주소 일치` · `이름 일치` · `○○상가 일치` · `같은 동네` · `링크 정보`<br>주의: `이름 일부만 같아요` · `이름이 비슷해요` · `주소 다름` · `같은 이름의 다른 지점` | 일치는 초록, 주의는 주황 배지 |
| `already_saved` | 요청의 `saved_place_ids`에 있으면 true | "이미 저장됨" 배지 |

### RecommendResult — 코스 추천 결과
```json
{
  "status": "ok",
  "region": { "region_id": "jamsil", "name": "잠실" },
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
- `source`는 `mine`(내 보관함) · `couple`(공동 보관함) · `external`(외부 추천) 중 하나다.
- `external=true`인 장소에는 **외부 추천** 배지를 붙인다. 이 장소는 백엔드가 `Place` 그대로 저장하면 된다.
- `signature`는 코스를 식별하는 값이다(장소 ID를 정렬해 이어 붙임). "다시 추천받기" 때 보낸다.

---

## 3. 상태값 (`data.status`)

### 3.1 장소 인식

| status | 화면 | 다음 동작 |
|---|---|---|
| `candidates` | 후보 확인 ("이 장소가 맞나요?" / "장소 N곳을 찾았어요") | 사용자가 고른 `Place`를 백엔드가 보관함에 저장 |
| `no_match` | 직접 검색 | 검색창에 `suggested_query`를 미리 채움 |
| `recognition_failed` | 스크린샷 인식 실패 | [직접 검색] / [다른 이미지 선택] |
| `link_unreadable` | 링크 읽기 실패 (인스타 로그인 벽, 네이버 지도 robots.txt 등) | [직접 검색] / [스크린샷] / 앱 '공유 → 복사' 문구 붙여넣기 |
| `search_failed` | 외부 검색 실패 | [다시 시도] / [직접 검색] |

### 3.2 코스 추천

| status | 화면 | 다음 동작 |
|---|---|---|
| `ok` | 코스 1/2/3 | [이 코스 선택] [다시 추천받기] |
| `unsupported_region` | 지원하지 않는 지역 | [다른 기준 선택]. 안내 문구는 `message` |
| `not_enough_candidates` | 후보 부족 | [다른 기준 선택] [장소 더 저장하기]. **지역을 자동으로 넓히지 않음** |
| `external_api_failed` | 외부 API 실패 | [다시 시도]. 이번에는 코스를 만들지 않음 |
| `no_result` | 결과 없음 (다시 추천해도 새 코스 없음) | [다른 기준 선택] |
| `anchor_not_found` | 기준 장소 없음 | 보관함에서 다시 선택 |

---

## 4. 엔드포인트 — AI 서버 (FastAPI, 접두사 `/ai/v1`)

| # | 메서드 · 경로 | 화면 | 요청 | 응답 `data` |
|---|---|---|---|---|
| 1 | `POST /ai/v1/places/resolve` | 장소 추가(링크·캡션) → 후보 확인 | JSON | `ResolveResult` |
| 2 | `POST /ai/v1/places/resolve/screenshot` | 장소 추가(스크린샷) → 후보 확인 | **multipart** | `ResolveResult` |
| 3 | `GET /ai/v1/places/search?q=` | 직접 검색 | 쿼리 | `ResolveResult` (groups 비어 있음) |
| 4 | `POST /ai/v1/places/nearby` | 장소 상세 › 주변 놀거리 | JSON | `{candidates: [{place, source}]}` |
| 5 | `POST /ai/v1/recommendations` | 로딩 → 코스 1/2/3 / 실패 | JSON | `RecommendResult` |
| 6 | `POST /ai/v1/recommendations/replacements` | 코스 편집 › 교체 시트 | JSON | `{candidates: [{place, source}]}` |
| 7 | `GET /ai/v1/regions` | 기준 선택 › 지역 | — | `{regions: [{region_id, name, lat, lng, radius_m}]}` |
| — | `GET /health` | 운영 확인 (키 없이) | — | `{status, workflow_version, search_provider, extractor, ocr, ocr_ready, auth_required}` (봉투 없음) |

**공통**
- 인증: `AI_SERVICE_KEY`를 설정하면 모든 `/ai/v1/*` 요청에 `X-AI-Key: <키>` 헤더가 필요하다. 설정하지 않으면 키 없이 열린다(로컬 개발용).
- 사용자 데이터는 **요청에 담아 보낸다**: `saved_places`(저장 장소, 최대 500곳)와 `saved_place_ids`(이미 저장 표시용, 최대 2000개). AI 서버는 이 데이터를 보관하지 않는다.
- 응답은 모두 `{ok, data}` / `{ok:false, error}`다(§1.1).
- 느린 작업(크롤링·OCR·네이버 검색)이 있어서 엔드포인트는 스레드풀에서 동기로 돈다. 스크린샷 인식은 동시에 `AI_OCR_CONCURRENCY`개(기본 2개)까지만 처리한다.
- 권장 타임아웃(백엔드 → AI): 링크·스크린샷 30초, 추천 15초, 나머지 10초

### 4.1 장소 인식 (링크·캡션) — `POST /ai/v1/places/resolve`
```jsonc
// 링크 — url 에 앱 '공유 → 복사' 문구 전체를 넣어도 된다 (첫 http 링크만 쓰고 나머지 문구는 장소 단서로 사용)
{ "type": "link", "url": "https://www.instagram.com/reel/xxx", "note": "(선택) 캡션 붙여넣기",
  "saved_place_ids": ["nv_..."] }
// 캡션만
{ "type": "text", "note": "1. 오지다 (서울 송파구 백제고분로48길 24) ...", "saved_place_ids": [] }
```
- 응답: `ResolveResult`
- 링크 수집 원칙
  - robots.txt를 지키고, 호스트마다 1초 간격을 둔다.
  - 네이버 지도·플레이스는 robots.txt가 막아서 읽지 않는다. 인스타는 로그인 벽이 있으면 `link_unreadable`이다.
  - 둘 다 `note`에 캡션이나 공유 문구가 있으면 그 텍스트로 계속 진행한다.
- 링크 하나에서 최대 10곳까지 인식한다. **저장하지 않는다.** 사용자가 고른 `Place`는 백엔드가 저장한다.

### 4.2 장소 인식 (스크린샷) — `POST /ai/v1/places/resolve/screenshot`
`multipart/form-data`
| 필드 | 형식 | 설명 |
|---|---|---|
| `files` | 파일 1~5개 | png·jpg·jpeg·webp·gif, 장당 최대 10MB(`AI_MAX_IMAGE_MB`). 여러 장이면 같은 장소의 여러 화면(홈·메뉴·정보 탭)으로 보고 합쳐 읽는다 |
| `note` | 문자열 (선택) | 함께 붙여넣은 캡션·메모 |
| `saved_place_ids` | 문자열, 여러 번 | 이미 저장한 place_id |

```bash
curl -X POST http://127.0.0.1:8001/ai/v1/places/resolve/screenshot \
  -H "X-AI-Key: $AI_SERVICE_KEY" -F "files=@capture.png" -F "saved_place_ids=nv_abc"
```
```python
# 백엔드(Python) 예: httpx
r = httpx.post(f"{AI}/ai/v1/places/resolve/screenshot", headers={"X-AI-Key": KEY},
               files=[("files", (f.filename, f.file, f.content_type)) for f in uploads],
               data={"note": note, "saved_place_ids": saved_ids}, timeout=30)
```
- 응답: `ResolveResult`
- 업로드한 이미지는 처리 후 바로 지우고 보관하지 않는다.
- 서버에 OCR이 없으면 `503 extractor_unavailable`이다.

### 4.3 직접 검색 — `GET /ai/v1/places/search?q=잠실 카페&saved_place_ids=nv_a&saved_place_ids=nv_b`
응답은 `ResolveResult`다. `groups`는 비어 있고 `candidates`에 검색 결과가 있다. 외부 검색이 실패하면 `status=search_failed`다.

### 4.4 코스 추천 — `POST /ai/v1/recommendations`
```json
{
  "anchor": { "type": "place", "place_id": "nv_a" },
  "anchor_place": { /* 기준 장소 Place (선택: 없으면 saved_places 에서 찾음) */ },
  "saved_places": [ { "place": { /* Place */ }, "source": "mine" },
                    { "place": { /* Place */ }, "source": "couple" } ],
  "exclude_signatures": []
}
```
- 응답: `RecommendResult`
- `anchor.type="region"`이면 `{"type": "region", "region_id": "jamsil"}`만 보내도 된다. 그래도 `saved_places`를 보내면 저장한 장소가 우선 들어간다.
- **다시 추천받기:** 앞에서 받은 `courses[].signature`를 **모두** 누적해 `exclude_signatures`로 보낸다.
- 기준 장소를 찾을 수 없으면(`anchor_place` 없음 + `saved_places`에도 없음) `status=anchor_not_found`다.
- `anchor.place_id`와 `anchor_place.place_id`가 다르면 400이다.
- 로딩 화면 문구 3개는 `steps`와 같다.

### 4.5 교체 후보 — `POST /ai/v1/recommendations/replacements`
```json
{ "course_places": [ { /* Place */ }, { }, { }, { } ], "index": 1, "saved_places": [ ], "limit": 8 }
```
- 응답: `{ "candidates": [ { "place": Place, "source": "mine|couple|external" } ] }`
- 앞·뒤 장소 **양쪽 모두에서** 도보 10분 이내인 곳만 고른다. 저장한 장소가 먼저 나온다. 코스에 이미 있는 장소는 뺀다.
- `index`가 범위를 벗어나면 400이다.

### 4.6 주변 놀거리 — `POST /ai/v1/places/nearby`
```json
{ "place": { /* Place */ }, "saved_places": [ ], "limit": 3 }
```
- 응답: `{ "candidates": [ { "place": Place, "source": ... } ] }`
- 걸어서 10분 이내의 놀거리·카페를 저장한 장소 먼저 보여준다. 외부 검색이 실패하면 저장한 장소만 돌려준다(에러 아님).

### 4.7 지원 지역 — `GET /ai/v1/regions`
응답은 `{ "regions": [ { "region_id": "jamsil", "name": "잠실", "lat": 37.511, "lng": 127.098, "radius_m": 1500 } ] }`다. 중심 좌표·반경은 근사값이다.

> "추천 조건 확인" 화면 문구(도보 · 반경 1km · 장소 사이 10분 · 3~5곳)는 고정 규칙이라 AI 호출 없이 프론트·백엔드에서 표시한다(§5.3).

---

## 5. AI 판정·추천 규칙

### 5.1 후보 매칭 (`save_flow.match`)
- **exact (확실한 일치, 기본 선택)**
  - 캡션 주소의 **도로명+건물번호가 같고** 이름도 비슷하다.
  - 또는 공백·기호를 뺀 **이름이 같다**. "○○점" 지점명은 붙어도 된다(닭튜브 = 닭튜브 방이점). 단, 주소가 다르면 안 된다.
- **similar (비슷한 이름, 기본 선택 안 함)**
  - 이름 일부만 같다(오지다 ⊂ 회포차오지다).
  - 철자가 비슷하다(유사도 0.75 이상).
  - 이름은 같은데 주소가 다르다(다른 지점).
- **제외**: 이름이 무관하다.
- 1순위가 정해지면, 나머지 `이름 일치` 후보는 `같은 이름의 다른 지점`(similar)으로 내린다.
- 주소가 없는 장소는 캡션 속 건물·상가 이름("장미상가")과 같은 링크 장소들이 모인 구(예: 송파구)를 보조 근거로 쓴다.
- 스크린샷에서 상호명이 깨지면 정확히 읽힌 **주소로 검색**해서 같은 건물의 가게를 후보로 찾는다.

### 5.2 장소 추출 (`placeflow.pipeline`)
- 입력을 판별한다: 인스타·네이버 블로그·네이버 플레이스·naver.me·이미지·텍스트
- 수집(크롤링·OCR) → 추출(규칙 기반, LLM은 선택) → 분류(`taxonomy.py`) 순서로 처리한다.
- **OCR**: Tesseract `kor+eng`를 쓴다.
  - 이미지를 약 1500px 폭으로 확대한 뒤 전처리 3가지로 동시에 읽고, 품질 점수가 가장 높은 결과를 고른다.
  - 상호명 줄이 깨지면 다른 결과에서 상호명을 가져오고, 빠진 주소도 다른 결과에서 보충한다.
- **개인정보**: 개인 전화·이메일·@계정·주민번호 형태는 저장하지 않는다(`normalize.py`).

### 5.3 코스 추천 (`recommend.py`)

| 영역 | 규칙 | 코드 위치 |
|---|---|---|
| 이동 | 도보만. 도보 분 = 직선거리 × 1.3 ÷ 4.5km/h, 올림 | `walking.walk_minutes` |
| 범위 | 기준 반경 1,000m (`ANCHOR_RADIUS_M`), 장소 사이 도보 10분 이하 (`MAX_LEG_MIN`) | `walking.py` |
| 코스 | 3~5곳. 기준 장소는 반드시 포함하고 **위치는 상관없음**(처음·중간·끝) | `_search_paths` |
| 개수 | 최대 3개를 서로 다르게 고른다(겹치는 장소 1곳 → 2곳 순으로 완화) | `recommend` |
| 다시 추천 | `exclude_signatures`에 있는 코스는 다시 내지 않는다 | `recommend` |
| 지역 | 지원 지역 6곳. **자동으로 넓히지 않는다** | `regions.py` |
| 후보 | 내·공동 보관함(저장 가산점) + 외부 추천(네이버 지역검색 "지역명 + 업종", 최대 30곳). 같은 이름이 80m 안에 있으면 저장 장소로 본다 | `gather_candidates` |
| 점수 | 업종 다양성(최대 4종), 같은 업종 연속 감점, 식당 2곳·술집 1곳 초과 감점, 식당이나 카페 포함 가점, 도보 시간 감점, 4곳 코스 가점 | `_path_score` |
| 운영시간 | 데이터가 없으면 "방문 전에 운영시간을 확인해주세요."를 표시한다. 추천 필터에는 쓰지 않는다 | `domain.HOURS_NOTICE` |

---

## 6. Python 함수 레퍼런스 (방법 B: 백엔드에서 직접 import)

```python
# 0) FastAPI 백엔드 앱에 AI 엔드포인트를 그대로 붙이기 (HTTP 계약은 §4와 같음)
from placeflow.ai_api import register
register(backend_app)                    # backend_app 에 /ai/v1/* · /health · AI 에러 봉투(DomainError 등) 추가
# register(backend_app, prefix="/internal/ai/v1", with_health=False)   # 경로·health 를 바꾸고 싶을 때
# 요청 검증 오류(422)·전역 500 처리는 백엔드 앱의 기존 정책을 그대로 따른다(단독 AI 서버에서만 400 봉투로 바꿈)

# 장소 인식
from placeflow.cli import build_pipeline                     # build_pipeline(llm, model, geo, ocr)
from placeflow.v3.save_flow import candidates_from_records, search_candidates, match

pipe = build_pipeline("heuristic", None, "none", "auto")      # LLM 없이 규칙 기반 + OCR(있으면)
out = pipe.run(url_or_image_path, extra_text, more_images=None)  # → PipelineOutput(records, message, …)
res = candidates_from_records(out.records, search, "link" | "screenshot",
                              is_saved=lambda pid: pid in saved_ids, pipeline_message=out.message)  # → ResolveResult
res = search_candidates(search, "잠실 카페", is_saved)          # 직접 검색 → ResolveResult
match(name, branch, road_core, buildings, place, name_unsure=False)  # → ("exact"|"similar", score, reasons) | None

# 코스 추천 (사용자 데이터는 인자로 받음: 저장소에 의존하지 않음)
from placeflow.v3.recommend import RecommendRequest, recommend, replacement_candidates, nearby_places, signature_of
recommend(RecommendRequest(anchor=..., exclude_signatures=[...]),
          user_pool=[(Place, "mine"|"couple"), ...], search=search, anchor_place=Place | None)  # → RecommendResult
replacement_candidates(course_places: list[Place], index, user_pool, search, limit=8)  # → list[Cand(place, source)]
nearby_places(place, user_pool, search, limit=3)                                       # → list[Cand]

# 장소 검색
from placeflow.v3.search import get_search_provider, NaverLocalSearch, DemoSearch, ExternalSearchError
search = get_search_provider("auto")   # auto(키 있으면 네이버) | naver | demo | demo_fail
search.search("잠실 카페", display=5)  # → list[Place], 실패 시 ExternalSearchError

# 보조
from placeflow.v3.walking import distance_m, walk_minutes, walkable
from placeflow.v3.regions import REGIONS, get_region, region_of
```

---

## 7. 환경 변수

| 이름 | 용도 | 필수 |
|---|---|---|
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 네이버 지역검색 키. **NAVER API HUB**(네이버 클라우드 플랫폼 콘솔 › NAVER API HUB › Application › 인증 정보)에서 발급. 현재 무료 기간, 검색 API 하루 25,000건 | 실서비스 필수. 없으면 데모 데이터 사용 |
| `NAVER_SEARCH_ENDPOINT` | `hub`(기본) 또는 `legacy`(개발자센터 기존 키, 2027-06-30까지) | 선택 |
| `OPENAI_API_KEY` · `ANTHROPIC_API_KEY` · `GEMINI_API_KEY` | 링크·스크린샷 정보 보강(LLM). 없어도 규칙 기반·OCR로 동작 | 선택 |
| `PLACEFLOW_LLM_MODEL` | LLM 모델 이름 | LLM을 쓸 때 |
| `TESSDATA_PREFIX` | Tesseract 언어 데이터 위치 (기본 위치가 아닐 때) | 선택 |
| `AI_SERVICE_KEY` | 설정하면 `/ai/v1/*`에 `X-AI-Key` 헤더 필수 | 배포 시 권장 |
| `AI_SEARCH_PROVIDER` | `auto`(기본, 키 있으면 네이버) · `naver` · `demo` · `demo_fail` | 선택 |
| `AI_LLM` · `AI_LLM_MODEL` | 추출기 `heuristic`(기본) · `openai` · `anthropic` · `gemini` / 모델 이름 | 선택 |
| `AI_OCR` | `auto`(기본) · `tesseract` · `none` | 선택 |
| `AI_OCR_CONCURRENCY` | 스크린샷 동시 처리 수 (기본 2) | 선택 |
| `AI_MAX_IMAGE_MB` | 이미지 장당 최대 크기 (기본 10) | 선택 |
| `AI_CORS_ORIGINS` | 쉼표로 구분한 허용 출처. 기본은 끔(백엔드끼리만 호출) | 선택 |

`.env`는 커밋하지 않는다.

---

## 8. 테스트

```bash
python3 -m pip install -r requirements-api.txt
python3 -m pytest -q tests/test_v3.py tests/test_ai_api.py   # AI 로직 + FastAPI 계약 (네트워크 불필요, 네이버는 가짜 검색)
python3 -m placeflow api --port 8001                         # → http://127.0.0.1:8001/docs 에서 직접 호출해 보기
```
실제 사례 테스트 데이터: `tests/fixtures/ig_jamsil_4places.txt` (인스타 '잠실 가성비 맛집 4곳' 캡션)

---

## 9. 미정(TBD) · 주의

- **네이버 지역검색은 실제 키로 호출해 확인하지 못했다.** 응답 파싱은 공개 문서 기준이다(`mapx/mapy` = WGS84, ×1e7 정수면 자동 환산, `<b>` 태그 제거).
- 지원 지역 6곳의 중심 좌표·반경(`regions.py`)은 **근사값**이다. 기획에서 확정한 경계로 바꿔야 한다.
- `place_id`가 이름+주소 해시라서 가게가 이전하거나 이름을 바꾸면 다른 장소로 잡힌다.
- OCR 품질은 Tesseract 버전과 한국어 데이터에 따라 달라진다. AI 서버를 배포하는 서버에도 `tesseract` + 한국어 데이터(`kor`)를 설치해야 스크린샷을 처리할 수 있다.
- 실험 서버(`python -m placeflow serve`)의 `/api/v3/*`는 실험 화면 전용이다. 백엔드 연동에는 `/ai/v1/*`를 쓴다.

# placeflow — 장소 저장 → 도보 데이트 코스 추천 (V3)

> **V3 (Figma `V3 - 재원` 확정 IA 기준)**
> - 장소 저장은 링크·스크린샷·직접 검색으로 찾은 **후보를 확인한 뒤 보관함에 저장**합니다.
> - 추천은 **기준 장소(또는 지원 지역 6곳) 반경 1km, 도보만, 장소 사이 10분 이내, 3~5곳 코스 3개**를 만듭니다.
> - 코스 상세에서는 항목·금액(2인 합계)을 적고, 편집(순서 바꾸기·교체·삭제·추가)한 뒤 저장합니다.
> - 백엔드·프론트 연결 규약: **[docs/API_CONVENTION.md](docs/API_CONVENTION.md)**
> - 코드: `placeflow/v3/` (service · api · domain · recommend · save_flow · search · repo · walking · regions)
> - 실험 화면: `python -m placeflow serve` → `/` (V3 모바일 흐름). 이전 화면은 `/legacy`
> - 외부 장소 검색: 네이버 지역검색 (`NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET`). 키가 없으면 가상 데모 데이터를 씁니다.
>
> 아래는 v0.2 설명입니다. 추출 파이프라인은 V3 에서도 그대로 씁니다. 컨셉 코스 추천(`route.py`)은 legacy 입니다.

20대 커플이 인스타그램·네이버에서 저장한 **링크나 캡쳐**를 장소 정보로 정리하고,
그날의 **데이트 컨셉**(맛집투어·액티비티·기념일 …)에 맞춰 **영업시간·이동시간·예산**을 지키는 하루 코스를 짜 줍니다.
유료 데이터 API 없이 동작합니다(링크 크롤링 + 무료 OCR). LLM 은 선택 사항입니다.

```
저장   링크/캡쳐(여러 장)/메모 → 판별 → 수집(크롤링·OCR) → 추출 → 검증 → 정보 보강(영업시간 구조화·체류시간·비용) → PlaceRecord
추천   날짜·시간·컨셉·이동수단·지역·예산 → 후보 거르기 → 슬롯 채우기(빔 탐색) → 영업시간·시간·예산 제약 → 코스 3개
```
| 문서 | 내용 |
|---|---|
| [docs/API_CONVENTION.md](docs/API_CONVENTION.md) | **V3 연결 API·함수·에러 코드·데이터 모델·비즈니스 규칙** |
| [docs/03_product_plan.md](docs/03_product_plan.md) | 재기획: 사용자 흐름, MVP, **장소 정보 항목·우선순위**, 컨셉별 코스 규칙 |
| [docs/04_data_sources.md](docs/04_data_sources.md) | 무료 데이터 출처 조사 (크롤링 원칙, OCR 실측, 이동시간 추정) |
| [docs/02_workflow.md](docs/02_workflow.md) | 저장 파이프라인 설계 |
| [docs/01_research.md](docs/01_research.md) | v0.1 수집 방법 조사 |

## v0.2 에서 추가된 것
- **코스 추천** (`placeflow/route.py`): 컨셉 9종 × 이동수단 4종, 영업시간·휴무·브레이크·라스트오더 준수, 식사 간격 3시간, 빈 시간에 '틈새 구경' 자동 삽입, 대안 장소·주의사항·추천 이유
- **영업시간 구조화** (`placeflow/hours.py`): "월-금 11:30~21:00 / 토,일 12:00~22:00", "매주 월요일 휴무", "브레이크타임", "L.O", 자정 넘김 등
- **장소 정보 확장**: 1인 예상 비용, 체류시간, 예약 방식(캐치테이블/N예약…), 평점·리뷰 수, 가까운 역, 주차, 편의, 실내/실외, **필드별 출처(provenance)**, 비어 있는 핵심 정보(`missing_fields`)
- **캡쳐 여러 장 → 한 장소**: 플레이스 홈·메뉴·정보 탭을 같이 올리면 합쳐서 추출
- **Tesseract OCR(무료)**: 플레이스 화면 캡쳐 전용 파서 (실제 캡쳐로 검증)
- **크롤링 원칙**: robots.txt 준수, 호스트당 1초 간격
- 실험 화면에 **② 코스 추천** 탭, 다녀온 곳 표시

## 빠른 시작 (API 키 없이)
```bash
pip install -r requirements.txt
python -m pytest -q                 # 테스트
python eval/run_eval.py             # 평가 → eval/report.md

# 텍스트 한 건
python -m placeflow extract "📍카페 온담 성수점 서울 성동구 서울숲2길 18 2층 딸기케이크 8,500원 #기념일"

# 오프라인 픽스처로 링크 흉내 (가상 데이터)
python -m placeflow extract https://blog.naver.com/fakeblog/220000000002 \
  --fixtures eval/fixtures/pages --geo fixture --trace
```

## 무료 OCR 설치 (캡쳐 읽기)
```bash
brew install tesseract tesseract-lang     # macOS (한국어 데이터 포함)
tesseract --list-langs | grep kor         # kor 이 보이면 준비 완료
```
설치 후 서버를 다시 켜면 실험 화면의 OCR 선택지에서 'Tesseract'가 기본으로 선택됩니다.

## 실험용 웹 화면
```bash
python -m placeflow serve          # → 브라우저에서 http://127.0.0.1:8000
```
- **① 장소 저장**: 링크·텍스트·캡쳐(최대 5장)를 넣으면 장소 카드(영업시간·1인 비용·체류시간·평점·예약·역·편의)를 만들고, 비어 있는 핵심 정보를 알려 줍니다.
- **② 코스 추천**: 컨셉·날짜·시간·이동 수단·지역·예산을 고르면 코스 3개(시간표·구간 이동시간·비용·동선 그림)를 보여 줍니다. 저장한 장소가 적으면 '가상 샘플 18곳'으로 체험할 수 있습니다.
- 코스 평가: `python eval/course_eval.py` → `eval/course_report.md` (가상 시나리오 6개, 하드 제약 위반 0건 확인)
- 링크·텍스트 입력, 캡쳐 이미지 업로드(끌어다 놓기·붙여넣기 가능), 가상 샘플 10개를 눌러 바로 실행할 수 있습니다.
- 결과 카드(분류·태그·주소·가격대·신뢰도·검토 사유), JSON, 실행 단계(trace)를 탭으로 봅니다.
- "저장" 을 켜면 `data/places.jsonl` 에 쌓이고, 아래 "저장된 장소" 에서 카테고리별로 걸러 볼 수 있습니다(같은 장소는 병합).
- LLM·지도 API는 서버를 띄운 터미널에 환경변수를 넣어 두면 선택지에 활성화됩니다. 127.0.0.1 에서만 열리는 실험용 서버입니다.

## 실제 LLM·지도 API 사용
LLM은 **교체 가능**합니다. `--llm` 으로 고르고, 모델 이름은 `--model` 또는 `PLACEFLOW_LLM_MODEL` 로 넣습니다.
```bash
pip install anthropic            # 또는 openai / google-genai
export ANTHROPIC_API_KEY=...     # .env.example 참고
export KAKAO_REST_API_KEY=...    # 또는 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET

python -m placeflow extract ./캡쳐.png --llm anthropic --model <모델명> --geo kakao --store data/places.jsonl
python -m placeflow extract "https://blog.naver.com/..." --llm openai --model <모델명> --geo naver
python eval/run_eval.py --llm gemini --model <모델명>   # 같은 정답셋으로 모델 비교
```
| 설정 | 값 | 설명 |
|---|---|---|
| `--llm` | `heuristic`(기본) · `openai` · `anthropic` · `gemini` | heuristic 은 규칙 기반 기준선, 이미지는 OCR 필요 |
| `--geo` | `none`(기본) · `kakao` · `naver` · `fixture` | 장소 확정·좌표 보강 |
| `--ocr` | `none` · `tesseract` · `sidecar` | 비전 LLM이 없을 때 이미지 읽기 |
| `--note` | 문자열 | 사용자가 함께 붙여넣은 캡션 (인스타 링크가 막혔을 때 사용) |

새 LLM 을 붙이려면 `extract(system, user_text, images, schema) -> dict` 하나만 구현한 클래스를 `llm/providers.py` 의 `get_provider` 에 등록하면 됩니다.

## 결과 형식 (요약)
```jsonc
{
  "status": "complete",                     // complete | needs_review | needs_user_input | failed
  "records": [{
    "dedupe_key": "kakao:1234",
    "place": { "name": "카페 온담", "branch": "성수점",
               "address": { "road": "서울 성동구 …", "sido": "서울특별시", "sigungu": "성동구" },
               "location": { "lat": 37.54, "lng": 127.04 }, "external_ids": { "kakao_place_id": "1234" } },
    "classification": { "primary_category": "cafe", "sub_category": "dessert",
                        "tags": ["뷰맛집", "기념일"], "free_tags": ["성수카페"] },
    "details": { "signature_menus": [{ "name": "딸기 생크림 케이크", "price": 8500 }], "price_level": 1,
                 "opening_hours_text": "11:00 - 22:00", "closed_days_text": "매주 월요일 휴무" },
    "content": { "summary": "…", "cautions": ["웨이팅 있음"], "evidence": ["…"], "raw_excerpt": "(개인정보 마스킹)" },
    "confidence": { "overall": 0.89, "extraction": 0.8, "geo_match": 1.0 },
    "review_reasons": [],
    "embedding_text": "카페 온담 성수점 | 카페·디저트/디저트 | 서울특별시 성동구 | #뷰맛집 …"
  }],
  "message": null                           // needs_user_input 일 때 사용자 안내 문구
}
```
- 전체 스키마: [schema/place_record.schema.json](schema/place_record.schema.json), 예시: [schema/examples/](schema/examples/)
- 카테고리·태그 정의: [placeflow/taxonomy.py](placeflow/taxonomy.py) (수정 후 `python -m placeflow export-schema`)
- LLM 프롬프트: [placeflow/prompts/extract_system.md](placeflow/prompts/extract_system.md)

## 폴더 구조
```
placeflow/
  router.py        입력 판별 (인스타/네이버 블로그/플레이스/naver.me/이미지/텍스트)
  fetchers/        링크 수집 (HTTP 클라이언트 교체 가능, 오프라인 픽스처 지원)
  llm/             LLM 어댑터 (openai · anthropic · gemini) + 공통 인터페이스
  heuristic.py     LLM 없이 동작하는 규칙 기반 추출기 (기준선·장애 시 대체)
  geo.py           네이버/카카오 지역검색 + 매칭 점수
  pipeline.py      전체 오케스트레이션 · 신뢰도 · 상태
  models.py        데이터 모델 (JSON Schema 의 원본)
  taxonomy.py      카테고리 · 태그 · 가격대
  normalize.py     주소 파싱 · 개인정보 마스킹 · 중복키 · 임베딩 텍스트
  store.py         임시 JSONL 저장소 (중복 병합)
  hours.py         영업시간 파서 · 영업 중 판정
  enrich.py        체류시간·비용·실내 기본값, 필드별 출처
  route.py         하루 코스 추천 (컨셉·제약·빔 탐색·이동시간 추정)
  ocr.py           Tesseract / 사이드카 OCR
  server.py        실험용 로컬 웹 서버 (python -m placeflow serve)
  web/index.html   실험용 화면
eval/              평가 정답셋(가상 데이터) · 픽스처 생성기 · 평가 스크립트 · heldout/(검증용 별도 케이스)
schema/            내보낸 JSON Schema · 택소노미 · 예시
tests/             pytest
```

## 알려진 한계 (v0.2)
- **이동 시간은 직선거리 기반 추정치**입니다(무료 실시간 길찾기 API 없음). 화면과 결과에 "추정"으로 표시합니다.
- 네이버 플레이스 홈 탭에는 "17:00에 영업 시작"처럼 일부만 보여서, **요일별 영업시간은 '정보' 탭 캡쳐가 있어야** 정확합니다. 없으면 코스에서 "영업시간 미확인" 경고와 감점을 받습니다.
- 플레이스 페이지 크롤링 구조(내장 JSON)는 제 쪽에서 직접 접근할 수 없어 검증하지 못했습니다. robots.txt 가 막으면 요청하지 않고 캡쳐를 요청합니다.
- 코스 추천은 **저장한 장소 안에서만** 고릅니다. 좌표가 없는 장소는 동선을 계산할 수 없어 제외됩니다(지도 보강 또는 플레이스 링크로 채움).
- 코스 평가는 가상 장소 18곳·시나리오 6개 기준입니다. 실제 저장 데이터로 다시 확인이 필요합니다.

## 알려진 한계 (v0.1)
- **인스타그램 링크**는 비로그인 수집이 자주 막힙니다. 이때는 `needs_user_input` 으로 캡쳐나 캡션을 요청하는 흐름을 전제로 했습니다.
- **평가셋 10건은 가상 데이터**이고 휴리스틱과 같이 만들어져 100%가 나옵니다(과적합). 검증 단계에서 따로 만든 held-out 8건(`eval/heldout/`)은 처음에 **78%**(전 필드 일치 7/9)였고, 거기서 나온 실패를 고친 뒤에는 8/9입니다. 고친 뒤라 더는 held-out이 아니므로, 실제 캡쳐·링크 20~30건으로 새 정답셋을 만들어 LLM 별로 비교하는 것이 다음 단계입니다.
- 개인정보: 저장되는 `raw_excerpt` 에서 주민번호 형식·이메일·@계정·휴대폰 번호를 가리고, 휴대폰(01x) 번호는 장소 전화번호로 저장하지 않습니다. 얼굴 등 이미지 속 개인정보는 원본 이미지를 저장하지 않는 것으로 대응합니다(이미지 보관 정책은 백엔드에서 결정).
- 링크 수집기는 사설·루프백 주소로 가는 요청과 리다이렉트를 막습니다(SSRF 기본 방어). 서버 배포 시에는 별도 프록시/허용 목록을 권장합니다.
- tesseract OCR 은 한국어 언어팩(`kor`)이 필요합니다. 평가의 이미지 케이스는 정답 OCR 텍스트(sidecar)를 쓰므로 실제 OCR 품질은 반영하지 않습니다.
- LLM 어댑터 3종은 SDK 파라미터 이름까지만 확인했고, **실제 API 키로 호출해 보지는 않았습니다.**
- 영업시간·메뉴는 원문 문자열로만 저장합니다(구조화 파싱은 추천 단계 요구가 정해진 뒤에).

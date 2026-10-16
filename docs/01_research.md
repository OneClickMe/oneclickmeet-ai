# T1. 데이터 수집 방법 조사 (researcher)

> 조사일: 2026-10-07. 사실(출처 있음)과 추론(⚠️ 표시)을 구분했습니다.

## 1. 입력 출처별 수집 가능성

| 입력 | 수집 방법 | 가능 여부 | 제약 | 근거 |
|---|---|---|---|---|
| 인스타그램 게시물/릴스 링크 | 공식 oEmbed (`/instagram_oembed`) | △ | Meta 앱 + `meta_oembed_read` 기능 필요. 2025년부터 `thumbnail_url`, `author_name` 미반환. 반환 필드는 `html`, `provider_name` 등이며 캡션을 별도 필드로 준다는 명시 없음 | [Meta oEmbed 업데이트](https://developers.facebook.com/blog/post/2025/04/08/oembed-updates/), [Instagram oEmbed 문서](https://developers.facebook.com/docs/instagram-platform/oembed) |
| 〃 | 페이지 HTML의 `og:title`/`og:description` 메타태그 | △ | ⚠️ 비로그인 요청은 로그인 벽·차단에 자주 막힘. Meta 스스로 "게시물 HTML 메타데이터에서 직접 썸네일을 생성하라"고 안내함 | 위 Meta 블로그 |
| 〃 | 비공식 스크래핑(Apify 등) | ✗ (권장 안 함) | 약관 위반 위험, 서비스 품질 불안정 | — |
| 〃 | **캡쳐 이미지 / 캡션 붙여넣기** | ○ | 가장 안정적인 경로 → 인스타는 **캡쳐 우선** 설계 | 추론 |
| 네이버 블로그 링크 | `m.blog.naver.com/{blogId}/{logNo}` 모바일 페이지 HTML + OG 메타 | ○ | ⚠️ PC 페이지는 본문이 iframe(`PostView.naver`) 안에 있으므로 모바일 URL로 바꿔서 가져오는 것이 단순함 | 추론(일반 관행) |
| 네이버 플레이스/지도 링크 | URL에서 place ID 추출 + OG 메타(상호명) | ○ | ⚠️ 상세 정보 페이지는 동적 렌더링 → 상호명만 얻고 **지역검색 API로 보강** | 추론 |
| `naver.me` 단축 링크 | HTTP 리다이렉트를 따라가 원래 URL 확인 | ○ | 리다이렉트 결과로 다시 라우팅 | 추론 |
| 캡쳐 이미지 | 비전 LLM(멀티모달) 또는 OCR(Tesseract 등) | ○ | OCR은 한글 정확도가 들쭉날쭉 → **비전 LLM 우선, OCR은 대안** | 추론 |

## 2. 장소 확정(보강)용 API

### 네이버 지역 검색 API
- 파라미터: `query`(필수), `display` 1~5(기본 1), `start`, `sort`=`random`(정확도)·`comment`(리뷰 수)
- 응답: `title`, `link`, `category`, `description`, `telephone`, `address`(지번), `roadAddress`, `mapx`, `mapy`
- 좌표: WGS84, `mapx`=경도, `mapy`=위도 (현재 문서 기준. ⚠️ 구 버전 응답은 정수 스케일(×10⁷) 형태도 있어 코드에서 둘 다 처리)
- 하루 호출 한도: 25,000회
- 출처: [NAVER API Hub – 지역 검색](https://api.ncloud-docs.com/docs/naver-api-hub-search-local)

### 카카오 로컬 API (키워드 장소 검색)
- `GET https://dapi.kakao.com/v2/local/search/keyword.json`
- 파라미터: `query`, `x`, `y`, `radius`, `size`(최대 15), `page`(최대 45), `category_group_code`
- 응답: `id`, `place_name`, `category_name`, `category_group_code`, `phone`, `address_name`, `road_address_name`, `x`(경도), `y`(위도), `place_url`
- 카테고리 그룹 코드(데이트 관련): `FD6` 음식점, `CE7` 카페, `CT1` 문화시설, `AT4` 관광명소, `AD5` 숙박
- 무료 쿼터는 개발자 계정당 처음 활성화한 앱에만 제공, 초과분은 유료
- 출처: [Kakao Local 공통](https://developers.kakao.com/docs/en/local/common), [Kakao Map REST API](https://developers.kakao.com/docs/en/kakaomap/rest-api)

## 3. 설계 결론 (builder에게 넘기는 결정사항)
1. **인스타그램 = 캡쳐/캡션 우선**, 링크는 OG 메타 시도 후 실패하면 `needs_user_input`으로 사용자에게 캡쳐를 요청.
2. **네이버 블로그 = 모바일 URL로 바꿔서 본문 수집**.
3. **네이버 플레이스 = place ID와 상호명만 취득 → 지역검색 API로 보강**.
4. 장소 확정은 **네이버·카카오 둘 다 어댑터로 제공**하고 설정에서 고름 (카카오는 결과가 많고 카테고리 코드가 깔끔, 네이버는 블로그·플레이스와 이름 표기가 일치).
5. LLM이 만든 주소는 **지도 API 결과와 일치할 때만 확정**, 아니면 신뢰도를 낮추고 사용자 확인 필요로 표시.

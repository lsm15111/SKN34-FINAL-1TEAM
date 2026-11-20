# 믿집 API 안내

[문서 목록](../README.md) · [개발 환경](../development.md) · [테스트와 QA](../testing.md) · [기능 개발표](../feature-roadmap.md)

이 문서는 **현재 등록된 v3·기존 v2 API**의 호출 주소·권한·오류·업무 순서를 설명합니다. 요청/응답 필드·필수값·enum의 정본은 해당 커밋의 `app.openapi()` 출력입니다. [v3 API 설계](../v3/api.md)는 의도와 화면 흐름을 설명하지만, 실제 제공 여부는 아래 등록 라우터와 구현을 따릅니다.

- **Swagger:** `http://localhost:8000/docs`
- **OpenAPI JSON:** `http://localhost:8000/openapi.json`
- `APP_ENV=local` 또는 `test`에서만 두 주소가 열립니다. `staging`·`production`에서는 Swagger·OpenAPI 경로가 비활성화되며 ReDoc은 제공하지 않습니다. 로컬·CI에서는 `app.openapi()`로 별도 생성할 수 있습니다.
- 확인 기준: **2026-11-19 `dev` `344f6dc1`(PR #151 반영)** 소스의 [라우터 등록](../../backend/app/main.py)과 `app.openapi()` 출력. **146개 경로·162개 HTTP API**(같은 경로에 여러 메서드면 별도 계산)입니다. 이 수치는 소스 기준이며 배포 서버의 버전·운영 검증을 뜻하지 않습니다.

인증 없이 지역 목록을 확인하는 간단한 예시:

```bash
curl http://localhost:8000/regions
```

### 빠른 이동

[주소·인증](#주소와-인증) · [오류·제한](#오류와-요청-제한) · [업무 순서](#주요-업무-흐름) · [전체 API 표](#등록된-api-162개)

## 주소와 인증

| 호출 위치 | 예시 | 주의 |
| --- | --- | --- |
| 백엔드 직접 | `http://localhost:8000/projects` | FastAPI 원본 경로는 `/projects` |
| Next.js 웹 | `http://localhost:3000/api/projects` | 같은 출처 `/api/*`를 Next.js가 백엔드 `/*`로 전달 |
| 배포 웹 | `https://<호스트>/api/projects` | Caddy가 `/api` 접두어를 제거; 호스트명은 배포 환경 확인 |

[Next.js rewrite](../../frontend/next.config.ts) · [Caddyfile](../../deploy/aws/Caddyfile). 아래 목록의 경로에는 **`/api`를 중복해서 붙이지 않습니다.**

- 인증은 **JWT Bearer가 아닌 서버 세션 쿠키**입니다. `POST /auth/signup`·`/auth/login`·`/auth/vendor-signup` 성공 시 쿠키가 발급되고, `POST /auth/logout`은 세션을 폐기합니다. 동일 출처의 웹 fetch에서는 `credentials: "same-origin"`을 사용합니다.
- `APP_ENV=local/test`에서는 `mj_sid` / `Secure=false`, `staging/production`에서는 `__Host-mj_sid` / `Secure=true`입니다(HTTPS URL을 자동 감지해 정하는 값이 아님). `HttpOnly`·`SameSite=Lax`·경로 `/`, 기본 14일입니다.
- 권한: **공개**는 세션 검사 없음, **로그인**은 활성 계정, **고객**은 고객 역할, **업체**는 승인 전 업체도 가능, **승인 업체**는 관리자 심사 승인 필요, **관리자**는 관리자 역할, **본인/관리자**는 집 주인 또는 관리자입니다. 고객·업체의 개별 자원 소유권도 서비스에서 검사합니다. `POST /me/withdraw`는 관리자 직접 탈퇴를 `403 admin_withdraw`로 제한합니다.
- Swagger에 자물쇠나 `security`가 없더라도 익명 API를 뜻하지 않습니다. 실제 `Depends(current_user)`·`require_role`·`approved_vendor`와 서비스의 소유권 검사를 사용합니다. `GET /stream`은 FastAPI 의존성 없이 쿠키를 직접 확인해 **로그인 필수**입니다.

## 오류와 요청 제한

오류는 원칙적으로 `{"error":{"code":"invalid","message":"입력한 내용을 확인해 주세요.","fields":[{"loc":["title"],"msg":"입력값을 확인해 주세요."}]}}` 모양입니다(`title` 필드는 합성 예시). `fields`는 필요할 때만 있고 오류 응답에 입력한 값이나 비밀번호를 넣지 않습니다.

**OpenAPI와 실행 오류의 차이:** FastAPI가 자동 생성한 422 스키마에는 `HTTPValidationError.detail`이 나오지만, 런타임의 커스텀 핸들러는 `422 invalid`와 `error.fields`로 응답합니다. 손상된 JSON도 422이며, 자동 명세에 없는 401·403·409도 서비스에서 발생합니다. 입력/성공 응답은 OpenAPI, 오류는 [errors.py](../../backend/app/shared/errors.py)와 각 service를 확인합니다.

| HTTP | `error.code` 예 | 처리 지침 |
| --- | --- | --- |
| 400·405 | `bad_request`·`method_not_allowed` | 요청 형식·메서드 확인(손상 JSON은 보통 422) |
| 401 | `login_required`·`bad_login` | 세션 또는 로그인 정보 확인 |
| 403 | `forbidden`·`vendor_not_approved`·`bad_origin`·`suspended`·`admin_withdraw` | 역할·업체 승인·Origin·계정 상태 확인 |
| 404 | `not_found` | 없는 자원, 다른 사람 자원, 만료된 상담 턴 등; 의미는 API마다 다름 |
| 409 | `stale`·`invalid_state`·`quote_changed`·`plan_changed`·`overlap`·`conflict` | 상태·버전 다시 조회 후 사용자 확인 |
| 413·415 | `too_large`·`file_too_big`·`file_type` | 본문/파일 상한·형식 확인 |
| 422 | `invalid`·`missing`·`file_kind` 등 | `fields`와 실제 요청 모델 확인 |
| 429 | `too_many_attempts` | `Retry-After`(초) 이후 재시도 |
| 500·503 | `server_error`·`unavailable` | 일시 장애. `GET /health/ready`는 예외적으로 자체 `status/checks` 형태의 503 |

`204` 성공은 응답 본문이 없고 파일 GET 성공은 바이너리입니다. 모든 성공/실패를 같은 JSON으로 처리하지 않습니다. [에러 처리](../../backend/app/shared/errors.py) · [파일 검사](../../backend/app/files/service.py).

| 제한 | 현재 값 |
| --- | --- |
| 본문 | 일반 JSON 1 MiB, `POST /guest/standard` 4 KiB, `POST /ai/turns` 16 KiB, `POST /threads/{thread_id}/messages` 8 KiB, `POST /v2/ask` 2 MiB, `POST /files` 21 MiB, 업체 가입 11 MiB |
| 개별 파일 | 사진·포트폴리오 10 MiB, 도면·견적/단가 문서 최대 20 MiB(`kind`별 내용 검사) |
| 가입·로그인 | 가입 IP당 시간당 10회, 로그인 IP당 15분 50회 + 이메일·IP당 10회 |
| 프로젝트·파일 | 사용자당 시간당 생성 30회, 업로드 120회 |
| AI 상담 시작 | `/v2/ask`와 `/ai/turns` 각각 사용자당 시간당 60회(`APP_ENV=local` 예외); `/ai/faq`는 IP당 분당 60회 |
| 손님 표준견적 | `/guest/standard`는 IP당 분당 20회·하루 300회(429); Redis가 안 되면 해당 손님 제한은 프로세스 안에서 계산 |

일반 Redis 요청 제한은 연결 실패 시 제한 검사만 통과시킵니다. 손님 제한은 위 예외가 있습니다. `429`는 `Retry-After` 헤더를 사용합니다. [request_guards.py](../../backend/app/shared/request_guards.py) · [ratelimit.py](../../backend/app/shared/ratelimit.py).

**Origin 검사는 CORS가 아닙니다.** `POST/PUT/PATCH/DELETE`와 `GET /stream`에서 `Origin`이 있으면 `ALLOWED_ORIGINS`(기본 `http://localhost:3000`, `http://localhost:3100`)와 비교하고, 없으면 `Sec-Fetch-Site`의 `same-origin` 여부, 이어 `Referer`를 확인합니다. 허용되지 않으면 `403 bad_origin`입니다. 모든 관련 헤더가 없는 서버·CLI 요청은 통과합니다. 현재 CORS 미들웨어가 없어 교차 출처 사전 요청에는 CORS 허용 헤더가 없습니다. 웹은 **같은 출처 `/api/*` 프록시**를 사용합니다. [OriginGuard](../../backend/app/shared/request_guards.py).

`SecurityHeaders`는 API 응답에 `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `X-Frame-Options: SAMEORIGIN`, `Cross-Origin-Resource-Policy: same-origin`, `Referrer-Policy: no-referrer`를 설정합니다. 파일·SSE의 개별 캐시·CSP 설정을 우선하며, 로컬 Swagger 페이지에는 CSP를 붙이지 않습니다. [보안 미들웨어](../../backend/app/shared/request_guards.py).

## 주요 업무 흐름

### 가입·손님 표준견적·업체 심사

1. 손님: `GET /regions`·`GET /regions/{sido}/{sgg}` → `POST /guest/standard`로 표준견적을 미리 계산합니다. 로그인 없이 사용하며 DB에 입력을 저장하지 않습니다. 가입하면 화면에서 `POST /projects`로 새 프로젝트를 만듭니다.
2. 고객: `POST /auth/signup` 또는 `/auth/login` → `GET /me` → 본인 프로젝트를 조회합니다.
3. 업체: 사업자등록증 포함 multipart `POST /auth/vendor-signup` → `GET /vendor/application`. 심사 전에도 신청 상태를 확인합니다.
4. 관리자: `GET /admin/vendors` → `POST /admin/vendors/{vendor_id}/review`(승인·보완·거절). 이미 결정된 신청은 `409 invalid_state`. 보완 시 `POST /vendor/application/resubmit`, 거절 후 `/vendor/application/reapply`.
5. 승인 업체: `GET/PUT /vendor/profile`(`updated_at` 불일치 `409 stale`), `GET /vendor/prices?trade=dobae` → `POST /vendor/prices/dobae/confirm`에 `base_version`·`lines`를 보내면 v3 단가를 한 번에 확인·저장합니다. 기존 `PUT /vendor/prices/dobae` 초안 저장 및 본문 없는 `POST .../confirm`도 호환됩니다. 근거 파일은 `POST /files`(`kind=price_doc`)로 먼저 올립니다. 외부 리뷰 링크는 `GET/PUT /vendor/review-links`에서 관리합니다. 승인 전 업체 기능은 `403 vendor_not_approved`입니다.

### v3 집 정보 → 업체 담기 → 실측 일정 → 견적 확정

1. 고객: `POST /projects`(`Idempotency-Key`), `GET /projects/{project_id}/standard`·`/plan` → `GET /projects/{project_id}/vendors?trade=dobae`. `POST /projects/{project_id}/shortlist`에서 업체를 담고 `GET .../shortlist`로 공종별 최대 3칸을 확인합니다.
2. `GET /projects/{project_id}/visits/draft?trade=dobae`로 담은 업체와 희망 기간 초안을 받고, `POST /projects/{project_id}/visits`에 `trade`·`vendor_ids`·`wish_start`·`wish_end`(필요하면 사진·벽지)를 보냅니다. v3 요청에는 연락처 동의 칸을 쓰지 않습니다. 201의 `created`·`failed`를 모두 확인합니다. **같은 URL의 구형 요청**은 희망 기간 없이 `share_contact_ids`·`consent_ver` 방식으로도 받으므로, v2 계약과 구분합니다.
3. 승인 업체: `GET /vendor/visits` → `GET /vendor/visits/{visit_id}` → `POST /vendor/visits/{visit_id}/window`(가능 기간·제외일·바로 확정 여부). 고객은 `GET /projects/{project_id}/visits/{visit_id}`에서 열려 있는 반나절을 보고 `POST .../pick` 합니다. 바로 확정이면 `booked`, 확인이 필요하면 `picked`가 되어 업체 `POST /vendor/visits/{visit_id}/accept` 또는 `.../propose`를 기다립니다. 일정 변경·재요청·실측 완료 경로는 아래 표를 따릅니다.
4. 승인 업체: `POST /files`(`kind=quote_doc`) → `PUT /vendor/visits/{visit_id}/quote`(임시 저장) → `POST /vendor/visits/{visit_id}/quote/send`(발송). 누락 칸은 `422 missing`·`fields`, 이미 발송한 동일 초안은 `409 already_sent`입니다.
5. 고객: `GET /projects/{project_id}/quotes?trade=dobae`로 비교 → `POST /projects/{project_id}/quotes/{visit_id}/confirm`(`seen_ver`). 버전이 바뀌면 `409 quote_changed`이며, 확정 시 같은 공정의 다른 요청을 닫습니다. 파일 조회의 `quote_id`는 **견적 버전 ID**, 확정의 `visit_id`는 **실측 요청 ID**입니다.

v3 실측 요청(합성 UUID·날짜 예시):

```json
{"trade":"dobae","vendor_ids":["00000000-0000-4000-8000-000000000001"],"wish_start":"2026-12-01","wish_end":"2026-12-08"}
```

### v3 고객·업체 채팅 → 공사 일정·완료·리뷰

1. 고객과 업체는 실측 확정 후 `GET /threads`, `GET /threads/{thread_id}/messages`로 대화를 확인하고 `POST .../messages`(`client_key` 중복 시 200)을 보냅니다. `POST .../read`는 읽은 번호를 기록하며, 차단은 고객의 `POST/DELETE .../block`입니다.
2. 업체: `GET /vendor/jobs/{deal_id}/dates/preview`(`start`·`end`·`crew`, 저장 없음) → `POST /vendor/jobs/{deal_id}/dates`로 v3 `days[]`·`crew` 제안(기존 `start/end` 입력 호환).
3. 고객: `GET /projects/{project_id}/schedule`에서 날짜·최신 `final_version` 확인 후 `POST /projects/{project_id}/deals/{deal_id}/dates/{proposal_id}/accept`. 본문은 **`{"seen_version":0}`** 같은 확정 공정표 버전(첫 버전은 0)입니다. 수락하면 새 확정 공정표 버전이 만들어집니다.
4. `409 plan_changed`는 본 공정표 버전 변경, `409 dates_changed`는 업체의 재제안, `409 overlap`은 공정 기간 겹침입니다. 다른 날짜 요청은 `POST .../date-requests`(최대 2회) → 업체 새 제안 → 고객 수락입니다.
5. 업체가 공사 중 추가 금액을 올리면 `POST /vendor/jobs/{deal_id}/extras`, 고객은 v3 `POST /projects/{project_id}/deals/{deal_id}/extras/{extra_id}/answer`(`approve|reject|ask`)로 답합니다. 구형 `.../ack`(`ok|talk`)도 등록돼 있습니다. 완료는 업체 `POST /vendor/jobs/{deal_id}/done` → 고객 `POST /projects/{project_id}/deals/{deal_id}/check`(`done|fixing`) 순서입니다. 끝난 공사의 고객만 `POST .../review`를 쓸 수 있고, 업체는 `PUT /vendor/reviews/{review_id}/reply`로 답글을 남깁니다.

### v3 AI 상담·실시간·신고

- `POST /ai/turns`는 **고객 전용**입니다. 필수 입력은 `client_key`·`text`이며, `context`(화면·내 프로젝트 등)·`chat_id`·`button`은 선택 입력입니다. 서버가 전체 답을 만든 뒤 정상 답을 DB에 **commit**하고 나서 SSE `token`(미리 완성된 **문장 단위**), `card`(화면 카드), `done`(`AiTurnOut` 전체)를 차례대로 보냅니다. **LLM이 생성 중인 토큰의 실시간 전송은 아닙니다.** 답 생성·저장 중 오류는 스트림 시작 전에 일반 오류로 응답합니다. `GET /ai/threads`·`/ai/threads/{chat_id}`는 내 대화, `GET /ai/faq`는 공개 FAQ입니다.
- `GET /stream`은 **로그인 필수 SSE** 알림 줄기이며, `ready`·`msg`·`read`·`notif`·`state`·`resync` 이벤트를 보냅니다. 이벤트에는 글·개인정보 본문 대신 식별자와 상태만 넣습니다. `Last-Event-ID` 재연결·15초 ping·60초 세션 재검사, 사용자당 5개 연결 제한이 있습니다. **등록된 WebSocket 엔드포인트는 없습니다.** [실시간 구현](../../backend/app/realtime/router.py).
- 고객·업체는 `POST /reports`로 채팅·업체·링크를 신고하고, 관리자는 `GET /admin/reports` → `GET /admin/reports/{report_id}` → `POST .../resolve`로 처리합니다. 회원 정지·업체 제한·리뷰 숨김 경로는 아래 관리자 표에 있습니다.

### v2 계산·AI 상담 (기존 경로 계약)

- `POST /v2/quote`·`/plan`·`/quick-budget`는 입력값 계산이며 자동 저장이 아닙니다. 평형·도면 미입력 시 32평 등 **가정값**으로 계산할 수 있으므로 `inp.assumed`를 확인합니다. `POST /v2/cases`는 고객의 새 건 생성(최대 30건), `PUT /v2/cases/{case_id}`는 선택값 `state`의 전체 저장과 견적·일정 **서버 재계산**입니다. 계산이 실패한 견적·공정표 결과는 비워질 수 있습니다.
- `POST /v2/ask`의 `kind=chat` 성공 완료는 대화를 저장하지만, `gate="out"`(범위 밖)·`failed=true`(모델·출력 검사 실패)는 **HTTP 200 안의 결과 값**이고 저장하지 않습니다. 설명용 `kind=quote_explanation|schedule`도 일반 대화 이력을 쓰지 않습니다. DB의 `rev` 충돌은 `409 conflict`입니다.
- `done=false`이면 응답의 `turn`·`tool_calls`을 받아 **브라우저에서 실제 도구**를 실행한 뒤 `POST /v2/ask/{turn_id}`에 해당 도구 ID별 `results`를 돌려줍니다. `set_home_info` 등 화면 도구는 제안이고 고객이 **[담기]**를 눌러야 선택값이 반영됩니다. 잘못된/중복 ID는 **422 invalid(턴 유지)**, 만료·다른 사용자의 턴·중복 재개의 늦은 요청은 **404 not_found**입니다(Redis TTL 10분).
- **위 `/v2/*` 계산·상담 경로에 한해** 결과·대화는 JSON으로 한 번에 응답합니다. v3에는 독립 `/ai/turns`·`/threads/*`와 `/stream` SSE가 별도로 등록돼 있으며, 일정 MCP HTTP API는 등록되지 않았습니다.

```json
{"kind":"chat","message":"도배 전에 무엇을 확인해야 하나요?"}
```

화면 도구의 **실제 실행 결과**를 제출하는 본문 형태(합성 ID이며 특정 도구의 실행을 보장하지 않는 예시):

```json
{"results":[{"id":"예시-도구-ID","content":"{\"ok\":true,\"saved\":false}"}]}
```

요청·응답 모델: [v2 스키마](../../backend/app/v2/schemas.py) · [상담 저장](../../backend/app/v2/ask_chat.py) · [프런트 확인 버튼](../../frontend/components/v2/ai/ask.tsx). 실제 화면·LLM·AWS QA는 별도 검사입니다.

## 등록된 API (162개)

FastAPI 원본 경로입니다. 동일 URL에서 메서드가 다르면 별도 API로 셉니다. **권한 표기:** 공개=세션 불필요, 로그인=활성 계정, 고객=고객 역할/본인 자원, 업체=업체 역할(승인 전 신청 API 포함), 승인 업체=관리자 승인된 업체, 관리자=관리자 역할, 본인/관리자=집 소유 고객 또는 관리자입니다. 원본 함수 링크와 권한은 [등록된 라우터](../../backend/app/main.py)·의존성·서비스 기준이며 자원별 접근은 추가로 확인합니다.

[상세 입력·성공 응답: Swagger UI](http://localhost:8000/docs) · [OpenAPI JSON](http://localhost:8000/openapi.json)

## 상태 확인 · 회원 · 계정 (8개)

코드: [FastAPI main](../../backend/app/main.py) · [회원 라우터](../../backend/app/auth/router.py) · [탈퇴 라우터](../../backend/app/account/router.py).

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| GET | `/health/live` | API 프로세스 상태 | 공개 | `main.live` |
| GET | `/health/ready` | DB·Redis 준비 상태, 장애 시 503 | 공개 | `main.ready` |
| POST | `/auth/signup` | 일반 고객 가입·세션 발급 | 공개 | `auth.signup` |
| POST | `/auth/login` | 이메일·비밀번호 로그인·세션 발급 | 공개 | `auth.login` |
| POST | `/auth/logout` | 기존 세션 폐기·쿠키 삭제(없어도 204) | 공개 | `auth.logout` |
| GET | `/me` | 로그인 사용자·권한·업체 승인 상태 | 로그인 | `auth.read_me` |
| PATCH | `/me` | 본인 정보 수정 | 로그인 | `auth.patch_me` |
| POST | `/me/withdraw` | 비밀번호 재확인 후 탈퇴·쿠키 삭제(관리자 직접 탈퇴는 403) | 로그인·관리자 제외 | `account.withdraw` |

## 파일·알림 (6개)

코드: [파일 라우터](../../backend/app/files/router.py) · [알림 라우터](../../backend/app/notify/router.py). 파일 조회의 `/files/{file_id}`는 올린 사람 또는 관리자만 사용할 수 있다. 견적·업체 사진은 **별도의 권한 확인을 거치는 경로**도 있다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| POST | `/files` | `kind`와 파일 업로드(multipart), 종류별 역할·크기 제한 | 로그인·파일 종류별 고객/업체 | `files.upload` |
| GET | `/files/{file_id}` | 업로드 파일 읽기 | 올린 사람/관리자 | `files.download` |
| GET | `/notifications` | 본인 알림 최근 50개(선택: 프로젝트) | 로그인 | `notify.list_notifications` |
| GET | `/notifications/unread` | 본인 미확인 알림 수 | 로그인 | `notify.unread` |
| POST | `/notifications/{nid}/read` | 알림 하나 읽음 처리(204) | 로그인·본인 | `notify.read_one` |
| POST | `/notifications/read-all` | 본인 알림 전체 읽음(204) | 로그인 | `notify.read_all` |

## 손님·집 프로젝트·표준견적 (8개)

코드: [손님 표준견적](../../backend/app/guest/router.py) · [프로젝트 라우터](../../backend/app/project/router.py) · [표준견적 라우터](../../backend/app/quote/router.py). `POST /projects`와 `GET /projects`는 서로 다른 라우터에 등록되어 있습니다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| POST | `/guest/standard` | 로그인 전 표준견적 계산(저장 없음, IP 제한·4 KiB) | 공개 | `guest.guest_standard` |
| GET | `/regions` | 시도·시군구 목록 | 공개 | `project.regions` |
| GET | `/regions/{sido}/{sgg}` | 해당 지역 읍면동 목록(자료 없으면 404) | 공개 | `project.region_emds` |
| POST | `/projects` | 고객 프로젝트 생성(201) | 고객 | `project.create_project` |
| GET | `/projects/{project_id}` | 한 집의 상세 정보 | 본인/관리자 | `project.get_project` |
| PATCH | `/projects/{project_id}` | 첫 실측 요청 전 집 정보 전체 수정 | 고객 | `project.update_project` |
| PUT | `/projects/{project_id}/checks/{key}` | 공사 전 준비 체크 상태 켜기·끄기 | 고객 | `project.set_check` |
| GET | `/projects/{project_id}/standard` | 저장된 표준견적 버전 조회·필요 시 계산 | 본인/관리자 | `quote.standard` |

## 업체 가입·심사·단가·프로필 (19개)

코드: [업체 라우터](../../backend/app/vendor/router.py) · [업체 승인 의존성](../../backend/app/vendor/deps.py).

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| POST | `/auth/vendor-signup` | 사업자등록증 포함 가입 신청·세션 발급(201) | 공개 | `vendor.vendor_signup` |
| GET | `/admin/vendors` | 업체 신청 목록·상태 검색 | 관리자 | `vendor.list_vendors` |
| GET | `/admin/vendors/summary` | 심사 상태별 수 | 관리자 | `vendor.vendor_summary` |
| GET | `/admin/vendors/{vendor_id}` | 업체 신청 상세·심사 기록 | 관리자 | `vendor.get_vendor` |
| POST | `/admin/vendors/{vendor_id}/review` | 승인·보완·거절 결정(중복 결정 409) | 관리자 | `vendor.review_vendor` |
| GET | `/vendor/application` | 본인 가입 심사·보완/거절 사유 조회 | 업체 | `vendor.my_application` |
| POST | `/vendor/application/resubmit` | 보완 요청 후 신청서 다시 제출 | 업체 | `vendor.resubmit` |
| POST | `/vendor/application/reapply` | 거절 후 같은 계정으로 재신청 | 업체 | `vendor.reapply` |
| GET | `/vendor/profile` | 승인된 업체 본인 정보 | 승인 업체 | `vendor.profile` |
| PUT | `/vendor/profile` | 프로필 저장(`updated_at` 버전 확인) | 승인 업체 | `vendor.save_profile` |
| POST | `/vendor/portfolio` | 먼저 올린 시공 사진을 프로필에 연결(201) | 승인 업체 | `vendor.add_portfolio` |
| DELETE | `/vendor/portfolio/{item_id}` | 시공 사진 연결 해제(204) | 승인 업체 | `vendor.remove_portfolio` |
| GET | `/vendor/prices` | 공종별 가견적 단가·근거 목록(`trade` 쿼리 필수) | 승인 업체 | `vendor.prices` |
| PUT | `/vendor/prices/{trade}` | 공종 단가 초안 전체 저장 | 승인 업체 | `vendor.save_prices` |
| POST | `/vendor/prices/{trade}/confirm` | 초안 단가 확정·이전 버전 보존 | 승인 업체 | `vendor.confirm_prices` |
| POST | `/vendor/price-files` | 업로드한 근거 파일 연결(201) | 승인 업체 | `vendor.add_price_file` |
| DELETE | `/vendor/price-files/{file_id}` | 단가 근거 파일 연결 해제(204) | 승인 업체 | `vendor.remove_price_file` |
| GET | `/vendor/review-links` | 내 외부 리뷰 링크 최대 3개·검토 상태 | 승인 업체 | `vendor.review_links` |
| PUT | `/vendor/review-links` | HTTPS 리뷰 링크 전체 저장(바뀐 링크는 검토 대기) | 승인 업체 | `vendor.save_review_links` |

## 업체 고르기·실측 요청·견적서 파일 (37개)

코드: [실측·업체 선택 라우터](../../backend/app/visit/router.py).

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| GET | `/projects/{project_id}/vendors` | 이 집·공종의 업체/가견적 목록 | 고객 | `visit.vendors` |
| GET | `/projects/{project_id}/vendors/{vendor_id}` | 이 집 기준 업체 상세와 가견적 | 고객 | `visit.vendor_detail` |
| GET | `/projects/{project_id}/vendors/{vendor_id}/photos/{file_id}` | 이 집에서 선택 가능한 업체의 시공 사진 | 고객 | `visit.vendor_photo` |
| POST | `/projects/{project_id}/visits` | v3 담은 업체·희망 기간·사진 또는 기존 연락처 동의 실측 요청(201) | 고객 | `visit.request_visits` |
| GET | `/projects/{project_id}/visits` | 업체별 실측 상태·다음 할 일·요청 목록 | 고객 | `visit.visits` |
| POST | `/projects/{project_id}/visits/{visit_id}/cancel` | 실측 요청 취소(상태별 제한·사유) | 고객 | `visit.cancel_visit` |
| POST | `/projects/{project_id}/visits/reselect` | 업체 확정 전 해당 공종 요청 모두 닫고 다시 고르기 | 고객 | `visit.reselect_visits` |
| GET | `/vendor/visits/{visit_id}` | 받은 실측 요청 상세·가능한 반나절 미리 보기 | 승인 업체 | `visit.vendor_visit` |
| GET | `/vendor/visits/{visit_id}/photos/{file_id}` | 해당 업체가 받은 요청 사진 열기 | 승인 업체 | `visit.vendor_visit_photo` |
| POST | `/vendor/visits/{visit_id}/decline` | 실측 요청 거절·사유 기록 | 승인 업체 | `visit.decline_visit` |
| POST | `/vendor/visits/{visit_id}/seen` | 새 요청 읽음 처리(204) | 승인 업체 | `visit.seen_visit` |
| GET | `/vendor/visits/{visit_id}/quote` | 실측 견적서 임시·발송 버전 목록 | 승인 업체 | `visit.quote_board` |
| PUT | `/vendor/visits/{visit_id}/quote` | 견적 파일 목록·요약 금액 등 임시 저장 | 승인 업체 | `visit.save_quote` |
| POST | `/vendor/visits/{visit_id}/quote/send` | 임시 견적서 보내기·재제출 | 승인 업체 | `visit.send_quote` |
| GET | `/projects/{project_id}/quotes/{quote_id}/files/{file_id}` | 받은 견적서의 발송 버전 파일 | 고객 | `visit.customer_quote_file` |
| GET | `/vendor/visits/{visit_id}/quote/files/{file_id}` | 내 실측 견적서 파일(임시 포함) | 승인 업체 | `visit.vendor_quote_file` |
| GET | `/projects/{project_id}/shortlist` | 공종별 담은 업체·남은 자리 | 고객 | `visit.shortlist` |
| POST | `/projects/{project_id}/shortlist` | 업체 담기(중복·자리 부족·견적 부재면 409) | 고객 | `visit.add_shortlist` |
| DELETE | `/projects/{project_id}/shortlist/{vendor_id}` | 담기 해제(요청이 살아 있으면 409, 204) | 고객 | `visit.remove_shortlist` |
| GET | `/projects/{project_id}/visits/draft` | 담은 업체와 실측 희망 기간 초안 | 고객 | `visit.visit_draft` |
| GET | `/projects/{project_id}/visits/{visit_id}` | 가능한 반나절·확정·제안·겹침 확인 | 고객 | `visit.visit_pick_view` |
| POST | `/projects/{project_id}/visits/{visit_id}/pick` | 고객이 반나절 선택(바로 확정·업체 수락 대기) | 고객 | `visit.pick_visit` |
| POST | `/projects/{project_id}/visits/{visit_id}/proposal/pick` | 업체가 제안한 반나절 선택·확정 | 고객 | `visit.pick_proposal` |
| POST | `/projects/{project_id}/visits/{visit_id}/repick` | 업체 제안을 거절하고 가능한 기간에서 재선택 | 고객 | `visit.repick_visit` |
| POST | `/projects/{project_id}/visits/{visit_id}/again` | 만료·취소 후 재요청(최대 2회 시도) | 고객 | `visit.request_again` |
| POST | `/projects/{project_id}/visits/{visit_id}/visited` | 실측 완료·업체 미방문 확인(반나절 종료 뒤) | 고객 | `visit.visited` |
| POST | `/projects/{project_id}/visits/{visit_id}/changes` | 확정한 실측 일정 변경 요청(201) | 고객 | `visit.request_change` |
| POST | `/projects/{project_id}/visits/{visit_id}/changes/{change_id}/withdraw` | 실측 변경 요청 철회 | 고객 | `visit.withdraw_change` |
| POST | `/projects/{project_id}/visits/{visit_id}/changes/{change_id}/pick` | 업체가 다시 제안한 변경 날짜 선택 | 고객 | `visit.pick_change` |
| POST | `/projects/{project_id}/visits/{visit_id}/requote` | 유효기간 지난 실측 견적 다시 요청 | 고객 | `visit.requote` |
| GET | `/projects/{project_id}/visits/{visit_id}/ics` | 확정 실측 일정 캘린더 파일(미확정 404) | 고객 | `visit.visit_ics` |
| POST | `/vendor/visits/{visit_id}/window` | 업체가 가능한 기간·제외일·즉시 확정 여부 답변 | 승인 업체 | `visit.answer_window` |
| POST | `/vendor/visits/{visit_id}/accept` | 고객이 선택한 반나절 수락·예약 확정 | 승인 업체 | `visit.accept_visit` |
| POST | `/vendor/visits/{visit_id}/propose` | 선택한 날짜 대신 반나절 1~3개 제안 | 승인 업체 | `visit.propose_visit` |
| POST | `/vendor/visits/{visit_id}/changes/{change_id}/accept` | 고객의 일정 변경 수락 | 승인 업체 | `visit.accept_change` |
| POST | `/vendor/visits/{visit_id}/changes/{change_id}/propose` | 일정 변경에 다른 반나절 제안 | 승인 업체 | `visit.counter_change` |
| GET | `/vendor/schedule` | 업체 실측 달력(반나절별 확정·보류·지역) | 승인 업체 | `visit.vendor_schedule` |

## 공정표·업체 확정·공사 일정·추가 금액 (30개)

코드: [업체 확정·공정표 라우터](../../backend/app/schedule/router.py). `GET /projects/{id}/plan`은 소유 고객·관리자 가능하지만 **`POST /projects/{id}/plan`은 서비스에서 고객만 허용**한다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| GET | `/projects/{project_id}/plan` | 예상 또는 확정 공정표 조회 | 본인/관리자 | `schedule.plan` |
| POST | `/projects/{project_id}/plan` | 예상 공정표 재계산·버전 저장 | 고객(서비스에서 역할 확인) | `schedule.redo_plan` |
| POST | `/projects/{project_id}/quotes/{visit_id}/confirm` | 본 견적 버전(`seen_ver`)으로 업체 확정 | 고객 | `schedule.confirm` |
| POST | `/projects/{project_id}/deals/{deal_id}/reselect` | 날짜 수락 전에 확정 업체 다시 고르기 | 고객 | `schedule.reselect` |
| GET | `/projects/{project_id}/deals` | 확정 업체 목록 | 고객 | `schedule.deals` |
| GET | `/projects/{project_id}/quotes` | 공종별 표준·업체 견적 비교 | 고객 | `schedule.compare_quotes` |
| GET | `/vendor/visits` | 업체 작업함(할 일·기다림·일정·공사·완료) | 승인 업체 | `schedule.vendor_inbox` |
| GET | `/vendor/visits/summary` | 작업함 탭별 수 | 승인 업체 | `schedule.vendor_inbox_summary` |
| GET | `/projects/{project_id}/schedule` | 공사 날짜 제안·요청·확정 버전 | 고객 | `schedule.schedule` |
| POST | `/projects/{project_id}/deals/{deal_id}/dates/{proposal_id}/accept` | 새 날짜 수락, 확정 공정표 버전 생성 | 고객 | `schedule.accept_dates` |
| POST | `/projects/{project_id}/deals/{deal_id}/date-requests` | 고객이 다른 날짜 요청(최대 2회, 201) | 고객 | `schedule.request_dates` |
| GET | `/vendor/jobs/{deal_id}` | 내 업체 공사 날짜·작업 보기 | 승인 업체 | `schedule.job` |
| GET | `/vendor/jobs/{deal_id}/dates/preview` | 저장 전 작업일·필요 인원·겹침 계산 | 승인 업체 | `schedule.preview_dates` |
| POST | `/vendor/jobs/{deal_id}/dates` | 업체 날짜 제안(`days[]` v3, `start/end` 기존 입력 호환) | 승인 업체 | `schedule.propose_dates` |
| POST | `/vendor/jobs/{deal_id}/extras` | 공사 중 추가 금액 등록(201) | 승인 업체 | `schedule.add_extra` |
| GET | `/vendor/jobs/{deal_id}/extras/preview` | 추가 금액·부가세·승인 후 합계 미리 계산(저장 없음) | 승인 업체 | `schedule.preview_extra` |
| GET | `/vendor/jobs/{deal_id}/extras/{extra_id}/files/{file_id}` | 추가 금액 공사 사진(업체용) | 승인 업체 | `schedule.vendor_extra_photo` |
| POST | `/projects/{project_id}/deals/{deal_id}/extras/{extra_id}/ack` | 기존 추가 금액 확인·상담(`ok/talk`) | 고객 | `schedule.ack_extra` |
| POST | `/projects/{project_id}/deals/{deal_id}/extras/{extra_id}/answer` | v3 추가 금액 승인·거절·채팅으로 문의 | 고객 | `schedule.answer_extra` |
| GET | `/projects/{project_id}/deals/{deal_id}/extras/{extra_id}/files/{file_id}` | 추가 금액 공사 사진(고객용) | 고객 | `schedule.customer_extra_photo` |
| POST | `/vendor/jobs/{deal_id}/done` | 업체 공사 완료·남은 일 완료 및 사진 보고 | 승인 업체 | `schedule.finish` |
| GET | `/projects/{project_id}/deals/{deal_id}/photos/{file_id}` | 고객의 공사 완료 사진 조회 | 고객 | `schedule.customer_done_photo` |
| GET | `/vendor/jobs/{deal_id}/photos/{file_id}` | 업체의 공사 완료 사진 조회 | 승인 업체 | `schedule.vendor_done_photo` |
| POST | `/projects/{project_id}/deals/{deal_id}/check` | 고객의 완료 확정·남은 일 확인(`done/fixing`) | 고객 | `schedule.check_work` |
| GET | `/projects` | 고객 소유 프로젝트 목록·상태 요약 | 고객 | `schedule.my_projects` |
| GET | `/projects/{project_id}/overview` | 집별 현재 할 일·단계·비용·업체 정보 | 고객 | `schedule.overview` |
| GET | `/projects/{project_id}/docs` | 프로젝트 표준·업체 견적·공정표 서류 모음 | 고객 | `schedule.docs` |
| GET | `/projects/{project_id}/log` | 한 공사 실측·견적·일정 이력 | 고객 | `schedule.project_log` |
| GET | `/projects/{project_id}/plan.ics` | 확정 공정표 날짜 캘린더 파일(미확정 404) | 고객 | `schedule.plan_ics` |
| GET | `/vendor/jobs/{deal_id}/log` | 업체 공사 한 건의 이력 | 승인 업체 | `schedule.job_log` |

## v3 AI 상담 (4개)

코드: [AI 라우터](../../backend/app/chat/router.py) · [대화 생성·저장](../../backend/app/chat/service.py). `POST /ai/turns`는 정상 답변을 만들고 저장한 뒤 문장·카드·완료 SSE를 보냅니다. 실패 결과는 `done.answer.failed`로 확인합니다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| POST | `/ai/turns` | AI 질문(저장 완료 후 문장 `token`·`card`·`done` SSE) | 고객 | `chat.turn` |
| GET | `/ai/threads` | 내 AI 대화 목록(프로젝트로 선택 조회 가능) | 고객 | `chat.threads` |
| GET | `/ai/threads/{chat_id}` | 내 AI 대화 메시지·번호표 조회 | 고객 | `chat.thread` |
| GET | `/ai/faq` | 로그인 전 자주 묻는 질문 칩(IP 요청 제한) | 공개 | `chat.faq` |

## 고객·업체 채팅 (8개)

코드: [대화 라우터](../../backend/app/thread/router.py). 고객·업체 모두 자기 대화만 접근할 수 있습니다. 채팅 본문에 상대의 개인정보를 담지 않고, 업체에게 고객 이름·연락처를 표시하지 않습니다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| GET | `/threads` | 내 고객·업체 대화 목록(최근 순) | 고객·업체 | `thread.threads` |
| GET | `/threads/{thread_id}` | 대화 머리·상태·상대·공사 연결(남의 대화 404) | 고객·업체 | `thread.thread` |
| GET | `/threads/{thread_id}/messages` | 메시지 조회(번호 커서, 기본 50·최대 100) | 고객·업체 | `thread.messages` |
| POST | `/threads/{thread_id}/messages` | 글·사진 보내기(중복 `client_key`는 기존 글 200) | 고객·업체 | `thread.post_message` |
| POST | `/threads/{thread_id}/read` | 읽은 메시지 번호 기록(204) | 고객·업체 | `thread.read` |
| GET | `/threads/{thread_id}/files/{file_id}` | 대화 당사자의 채팅 사진 조회 | 고객·업체 | `thread.thread_file` |
| POST | `/threads/{thread_id}/block` | 업체 차단·채팅 읽기 전용으로 변경 | 고객 | `thread.block` |
| DELETE | `/threads/{thread_id}/block` | 차단 해제(차단으로 닫힌 대화만) | 고객 | `thread.unblock` |

## 실시간 알림 SSE (1개)

코드: [실시간 라우터](../../backend/app/realtime/router.py) · [이벤트 서비스](../../backend/app/realtime/service.py). **인증은 의존성 목록에 드러나지 않아도 쿠키를 직접 검사합니다.** 로그인하지 않았으면 401, 연결 수 초과는 429입니다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| GET | `/stream` | 내 `ready/msg/read/notif/state/resync` 이벤트·재연결·ping SSE | 로그인 | `realtime.stream` |

## 리뷰 (7개)

코드: [리뷰 라우터](../../backend/app/review/router.py). 완료된 공사의 고객만 리뷰를 작성할 수 있고, 업체는 자기 리뷰에 답글을 답니다. 숨긴 리뷰의 사진은 작성자·해당 업체·관리자에게만 보입니다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| GET | `/projects/{project_id}/vendors/{vendor_id}/reviews` | 업체 리뷰 최신순·낮은 별점순 조회(숨김 제외) | 고객 | `review.vendor_reviews_for_customer` |
| POST | `/projects/{project_id}/deals/{deal_id}/review` | 완료된 공사의 고객 리뷰 작성(201, 중복 409) | 고객 | `review.write_review` |
| PATCH | `/reviews/{review_id}` | 내 리뷰 수정(수정됨 표시) | 고객 | `review.edit_review` |
| DELETE | `/reviews/{review_id}` | 내 리뷰 삭제(204) | 고객 | `review.delete_review` |
| GET | `/reviews/{review_id}/photos/{file_id}` | 리뷰 사진 조회(숨김 여부에 따라 본인·업체·관리자 제한) | 고객·업체·관리자 | `review.review_photo` |
| GET | `/vendor/reviews` | 업체가 받은 리뷰·답글 기다림 수 | 승인 업체 | `review.my_reviews` |
| PUT | `/vendor/reviews/{review_id}/reply` | 업체 답글 작성(201)·수정(200) | 승인 업체 | `review.reply` |

## 신고·관리자 조치 (12개)

코드: [신고·관리자 라우터](../../backend/app/report/router.py). 신고 대상 접근 가능 여부를 확인하고, 관리자 조치는 처리 내역을 남깁니다. 회원 정지는 세션을 폐기하며, 업체 제한은 범위(새 요청만 또는 진행 중 포함)에 따라 다릅니다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| POST | `/reports` | 내 대화·조회 가능한 업체·외부 링크 신고(201) | 고객·업체 | `report.report` |
| GET | `/admin/reports` | 신고 목록(처리 상태·종류 필터) | 관리자 | `report.admin_reports` |
| GET | `/admin/reports/{report_id}` | 신고 상세·신고된 글 안전한 표시 | 관리자 | `report.admin_report` |
| POST | `/admin/reports/{report_id}/resolve` | 신고 처리(경고·대화 제한·업체 정지·링크 숨김 등) | 관리자 | `report.resolve` |
| GET | `/admin/members` | 고객·업체 회원 검색·상태·가입일 | 관리자 | `report.members` |
| POST | `/admin/members/{user_id}/suspend` | 회원 정지·기존 세션 폐기 | 관리자 | `report.suspend_member` |
| POST | `/admin/members/{user_id}/unsuspend` | 회원 정지 해제 | 관리자 | `report.unsuspend_member` |
| POST | `/admin/vendors/{vendor_id}/suspend` | 업체 새 요청 제한 또는 진행 중 요청까지 정지 | 관리자 | `report.admin_suspend_vendor` |
| POST | `/admin/vendors/{vendor_id}/unsuspend` | 업체 제한 해제 | 관리자 | `report.admin_unsuspend_vendor` |
| POST | `/admin/vendors/{vendor_id}/links/{sort}` | 업체 외부 리뷰 링크 표시·숨김 심사 | 관리자 | `report.admin_check_link` |
| POST | `/admin/reviews/{review_id}/hide` | 리뷰 숨김·관리자 처리 기록 | 관리자 | `report.hide_review` |
| POST | `/admin/reviews/{review_id}/show` | 숨긴 리뷰 다시 표시 | 관리자 | `report.show_review` |

## v2 계산·AI 상담·저장 (22개)

코드: [v2 라우터](../../backend/app/v2/router.py). `/v2/ask`와 계산 API는 **로그인 필요(역할 제한 없음)**이고, `/v2/cases`는 **고객 역할만** 가능하다. v2 화면은 `wallpaper`(도배)만 노출하지만, 코드의 계산 입력 enum이 모든 화면 노출 기능을 뜻하지는 않는다.

| 메서드 | 원본 경로 | 기능 | 인증·역할 | 코드(함수) |
| --- | --- | --- | --- | --- |
| GET | `/v2/floor-plans` | 준비된 예시 평면도 목록 | 로그인 | `v2.plans` |
| GET | `/v2/floor-plans/{plan_id}/qty` | 예시 평면도 공간 수량 | 로그인 | `v2.plan_qty` |
| GET | `/v2/materials` | 목공 자재·고정 단가 항목 | 로그인 | `v2.materials` |
| POST | `/v2/projects/{project_id}/preview` | 기존 프로젝트 도면·자재 견적 미리보기(저장 안 함) | 본인/관리자 | `v2.preview` |
| POST | `/v2/quote` | v2 표준견적 계산(저장 안 함) | 로그인 | `v2.v2_quote` |
| GET | `/v2/market-extras` | 목공 추가 항목·시장 기준 자료 | 로그인 | `v2.v2_market_extras` |
| POST | `/v2/plan` | v2 예상 공정표 계산(저장 안 함) | 로그인 | `v2.v2_plan` |
| POST | `/v2/check` | 받은 견적 맞춰 보기 | 로그인 | `v2.v2_check` |
| POST | `/v2/estimate` | v2 업체 단가 기반 가견적 계산 | 로그인 | `v2.v2_estimate` |
| POST | `/v2/entered` | 실측 견적 입력액의 부가세·합계 계산 | 로그인 | `v2.v2_entered` |
| POST | `/v2/calc7` | 셀프 도배·몰딩·페인트 계산기 | 로그인 | `v2.v2_calc7` |
| POST | `/v2/extras-range` | 선택한 추가 항목 시장 범위 | 로그인 | `v2.v2_extras` |
| POST | `/v2/quick-budget` | 빠른 예산 범위·추가 질문 계산 | 로그인 | `v2.v2_quick` |
| POST | `/v2/ask` | AI 상담 한 턴 시작(도구·완료 JSON) | 로그인 | `v2.v2_ask` |
| POST | `/v2/ask/{turn_id}` | 화면 도구 결과 제출·턴 재개 | 로그인·본인 턴 | `v2.v2_ask_resume` |
| GET | `/v2/ask/health` | v2 AI 켜짐 상태(`ok`, `live`) | 로그인 | `v2.v2_ask_health` |
| GET | `/v2/cases` | 내 v2 인테리어 목록 | 고객 | `v2.cases` |
| POST | `/v2/cases` | v2 인테리어 한 건 생성(201) | 고객 | `v2.case_create` |
| GET | `/v2/cases/{case_id}` | 내 저장된 인테리어 열기 | 고객 | `v2.case_get` |
| PUT | `/v2/cases/{case_id}` | 전체 상태 저장·금액/공정표 재계산 | 고객 | `v2.case_save` |
| PATCH | `/v2/cases/{case_id}` | 저장한 인테리어 제목 변경 | 고객 | `v2.case_rename` |
| DELETE | `/v2/cases/{case_id}` | 내 인테리어 삭제(204) | 고객 | `v2.case_delete` |

### 이 앱에 등록되지 않은 경로

WebSocket 라우트·일정 MCP HTTP API·결제·전자계약·문서 OCR 엔드포인트는 등록돼 있지 않습니다. 채팅은 `/threads/*` HTTP, 실시간 알림과 AI 답변은 각각 `GET /stream`·`POST /ai/turns` SSE로 제공됩니다. 구현과 설계의 구분은 [기능 개발표](../feature-roadmap.md)와 [v3 API 설계](../v3/api.md)에서 확인합니다.

API 변경 시 라우터/스키마의 OpenAPI를 갱신하고, `frontend/`에서 `pnpm gen:api`로 생성된 `lib/backend/schema.d.ts`를 재생성합니다(직접 손수정 금지). 오류·권한·호출 순서가 바뀌면 이 문서도 함께 수정합니다.

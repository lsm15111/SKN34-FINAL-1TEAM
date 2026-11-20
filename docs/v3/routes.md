# 믿집 v3 화면 → 경로 (개발자)

- 쓴 날: 2026-11-18 · 기준: 9판 `design/screens.json`(109개, 표는 스크립트로 빠짐없이 만들었어요) · 지금 `frontend/app/**`
- 배치 규칙: `adr/dev-08`(같은 경로 + CSS 기준점 768 · 1024px). 웹(d) 화면은 같은 경로의 웹 배치예요.
- '묶음'은 `plan-build.md`의 제작 묶음(B2 고객 화면 · B3 업체 · 관리자 · B4 껍데기 · B5 AI 칸)이에요.

## 1. 경로 나무 (v3)

```
app/
  layout.tsx                         B4  뿌리: 글꼴 · 토큰 · LiveProvider(실시간 한 줄기) · 설치 안내
  manifest.ts                        B4  새로: PWA manifest
  page.tsx                           B2  / 홈(로그인 전 · 뒤)
  start/page.tsx                     B2  /start 기본 정보(?edit=id면 고치기 · 잠김)
  start/standard/page.tsx            B2  새로: /start/standard 로그인 전 표준견적서
  signup/page.tsx · login · reset-password   B2
  signup/vendor/page.tsx             B3
  my/page.tsx · notifications · account(+ phone 새로) · faq · legal   B2
  chat/layout.tsx                    B2  새로: 웹 2단(목록 + 대화) · 폰 한 단
  chat/page.tsx · chat/[threadId]/page.tsx   B2  새로(고객 · 업체 같이)
  projects/[id]/layout.tsx           B2  공사 띠(웹) · AiPanel 자리(B5 조각)
  projects/[id]/page.tsx             B2  요약 · 기록(?tab=log)
  projects/[id]/standard · plan · quotes(+ [visitId]/confirm) · schedule · docs   B2
  projects/[id]/vendors/page.tsx · [vid]/page.tsx · [vid]/reviews/page.tsx(새로)   B2
  projects/[id]/vendors/@panel/      B2  지움(9판 D07과 겹침, dev-08)
  projects/[id]/visits/page.tsx      B2  상태판
  projects/[id]/visits/new/page.tsx  B2  새로: 요청서
  projects/[id]/visits/[visitId]/page.tsx    B2  새로: 날짜 고르기 · 확정 · 제안 · 겹침 없음
  projects/[id]/review/page.tsx      B2  새로: 리뷰 쓰기
  vendor/page.tsx                    B3  작업함(?tab=todo|waiting|sched|jobs|done) · 처음 할 일 · 보완 · 거절
  vendor/requests/[visitId]/page.tsx (+ quote)   B3  기간 답하기 · 수락 · 제안 · 견적서
  vendor/jobs/[dealId]/page.tsx      B3  공사 한 건(날짜 · 추가 금액 · 공사 끝 · 기록)
  vendor/jobs/page.tsx               B3  → /vendor?tab=jobs로 보내기
  vendor/profile/page.tsx            B3  기본 · 사례 · 링크(?tab=)
  vendor/prices/[trade]/page.tsx     B3  새로: 도배 단가(1201~1208)
  vendor/reviews/page.tsx            B3  새로: 리뷰 · 답글
  admin/vendors · admin/reports(새로) · admin/members   B3
  not-found.tsx · error.tsx          B2
```

- 화면 안 창(시트 · 확인 창)은 경로를 만들지 않아요. 뒤로 가기로 닫혀야 하는 것(폰 AI 칸 `?ai=1` · 사진 크게 보기 `?photo=n`)만 주소에 얕게 붙여요(`history.pushState`).
- 권한: 고객 경로는 `requireRole('customer')`, 업체는 `'vendor'`, 관리자는 `'admin'`. `/chat/**` · `/notifications`는 고객 · 업체 둘 다(역할로 모양만 나눔). 남의 공사 · 대화는 C56 화면(404)이에요.
- 알림 · 메일 링크 대상: 고객 `/projects/{id}/visits/{vid}` · `/chat/{tid}` · `/projects/{id}/quotes` · `/projects/{id}/schedule` · `/projects/{id}/review`, 업체 `/vendor/requests/{vid}` · `/vendor/jobs/{did}` · `/vendor/reviews` · `/chat/{tid}`.
- 폰 아래 탭 바(B4): 고객 홈 `/` · 내 공사 `/my` · 채팅 `/chat` · 알림 `/notifications` · 내 정보 `/account` / 업체 작업함 `/vendor` · 채팅 `/chat` · 업체 정보 `/vendor/profile` · 알림 `/notifications`.

## 2. 화면 109개 표

- 정렬: 고객 폰(c) → 데스크톱(d) → 업체(v) → 관리자(a).
- 파일 표시: (새) 새 파일 · (고침) 있는 파일을 고침 · 표시 없음 그대로 써요. `{id}` = 공사, `{vid}` = 실측 요청, `{did}` = 업체 확정, `{tid}` = 대화.

| 코드 | 키 | 화면 | 9판 경로 | Next.js 경로 | 파일 | 묶음 | 폰 · 웹 배치 | 쓰는 API |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | `home0` | 홈 (로그인 전) (웹 짝 d_home) | `/ · 로그인 전` | `/ (로그인 전)` | app/page.tsx (고침) | B2 | 폰: 머리 '로그인' · 탭 바 없음 / 웹: D10 | POST /guest/standard(견본 입력, 서버에서 캐시) |
| C02 | `info` | 기본 정보 (웹 짝 d_info, 11-20 '도배 기본 정보'에서 바꿈) | `/start` | `/start` | app/start/page.tsx (고침) · components/start/* (고침) | B2 | 폰: 세 묶음 한 줄 / 웹: D11 오른쪽 '넣은 내용' 요약. 부분이면 공간 · 면 펼침 | GET /regions · /regions/{sido}/{sgg} · 로그인 전 답은 localStorage |
| C03 | `pyeong` | 평으로 넣기 | `/start · 시트` | `/start · 시트` | components/start/PyeongSheet.tsx (새) | B2 | 폰 아래 시트 / 웹 가운데 창 | 없음(평 → ㎡ 넣기 도움, 저장은 ㎡) |
| C04 | `signup` | 가입 고르기 | `/signup` | `/signup` | app/signup/page.tsx (고침) | B2 | 같음. 카카오 '준비 중' | 없음 |
| C05 | `email` | 이메일 가입 · 약관 동의 | `/signup` | `/signup?step=email` | components/auth/SignupForm.tsx (고침) | B2 | 같음. 제출할 때만 검사(I6 B) | POST /auth/signup → POST /projects(Idempotency-Key) |
| C06 | `login` | 로그인 | `/login` | `/login` | app/login/page.tsx | B2 | 같음. next로 이어 가기 | POST /auth/login |
| C07 | `std` | 표준견적서 (웹 짝 d_std) | `/projects/{id}/standard` | `/projects/{id}/standard` | app/projects/[id]/standard/page.tsx (고침) | B2 | 폰: 머리 'AI에게 묻기' / 웹: D01 공사 띠 + 옆 AI 칸 | GET /projects/{id}/standard |
| C08 | `plan0` | 예상 공정표 | `/projects/{id}/plan` | `/projects/{id}/plan` | app/projects/[id]/plan/page.tsx (고침) | B2 | 같음(날짜 머리 + 막대) | GET /projects/{id}/plan |
| C09 | `ai` | AI에게 묻기 (폰 전체 화면) (웹 짝 d_std) | `라우트 모달` | 경로 없음 · `?ai=1` | components/ai/AiPanel.tsx (새, B5) · 자리는 app/projects/[id]/layout.tsx (고침, B2) | B5 · B2 | 폰: 전체 화면(뒤로 가기로 닫힘) / 웹: 옆 칸(N2 A, D01 · D03 · D06 …) | POST /ai/turns · GET /ai/threads |
| C10 | `vendors` | 업체 보기 + 담기 띠 (웹 짝 d_vendors) | `/projects/{id}/vendors` | `/projects/{id}/vendors` | app/projects/[id]/vendors/page.tsx (고침) | B2 | 폰: 담기 띠 아래 고정 / 웹: D06 목록 아래 담기 카드 + 옆 AI 칸 | GET /projects/{id}/vendors · GET · POST · DELETE /projects/{id}/shortlist |
| C11 | `vdetail` | 업체 상세 (웹 짝 d_vdetail) | `/projects/{id}/vendors/{vid}` | `/projects/{id}/vendors/[vid]` | app/projects/[id]/vendors/[vid]/page.tsx (고침) · `@panel/(.)[vid]` 지움 | B2 | 폰: 탭(가견적 · 사례 · 리뷰) / 웹: D07 가견적 표 + 옆 AI 칸 | GET /projects/{id}/vendors/{vid}?grade= · POST /reports |
| C12 | `zero` | 업체 0곳 (다른 집 예시) | `/projects/{id}/vendors · 빈 상태` | `/projects/{id}/vendors · 빈 상태` | 같은 파일 | B2 | 같음(가까운 구 업체) | GET /projects/{id}/vendors(nearby) |
| C13 | `req` | 실측 일정 요청서 (웹 짝 d_req) | `/projects/{id}/visits · 요청서` | `/projects/{id}/visits/new` | app/projects/[id]/visits/new/page.tsx (새) | B2 | 폰: 사진 눌러서 고르기 / 웹: D08 달력 + 끌어다 놓기 + AI 초안 카드 | GET /projects/{id}/visits/draft · POST /files(photo) · POST /projects/{id}/visits |
| C14 | `board1` | 실측 일정 (업체 답이 옴) (웹 짝 d_visit) | `/projects/{id}/visits` | `/projects/{id}/visits` | app/projects/[id]/visits/page.tsx (고침) | B2 | 폰: 업체 카드 / 웹: D03 비교표(업체 = 열) + AI 칸 | GET /projects/{id}/visits |
| C15 | `reqview` | 요청 내용 보기 | `/projects/{id}/visits · 시트` | `/projects/{id}/visits · 시트` | components/visit/RequestSheet.tsx (새) | B2 | 폰 시트 / 웹 가운데 창 | GET /projects/{id}/visits(머리) |
| C16 | `pick_on` | 날짜 고르기 · 바로 확정 (웹 짝 d_pick_on) | `/projects/{id}/visits · 날짜 고르기` | `/projects/{id}/visits/[visitId]` | app/projects/[id]/visits/[visitId]/page.tsx (새) | B2 | 폰: 달력 + 아래 띠 / 웹: D15 큰 달력 + 오른쪽 반나절 + AI | GET /projects/{id}/visits/{vid} · POST …/pick |
| C17 | `done` | 실측 확정됨 | `/projects/{id}/visits · 확정` | `/projects/{id}/visits/[visitId] · 확정` | 같은 파일 | B2 | 같음. .ics 받기 | GET /projects/{id}/visits/{vid}/ics |
| C18 | `board_exp` | 실측 일정 (답 없음) | `/projects/{id}/visits` | `/projects/{id}/visits` | 같은 파일(상태판) | B2 | 같음 | POST /projects/{id}/visits/{vid}/again |
| C19 | `pick_off` | 날짜 고르기 · 업체가 수락 (웹 짝 d_pick_off) | `/projects/{id}/visits · 날짜 고르기` | `/projects/{id}/visits/[visitId]` | 같은 파일 | B2 | 폰 / 웹: D16. 단추 '○○에 보내기' | POST /projects/{id}/visits/{vid}/pick |
| C20 | `board_prop` | 실측 일정 (다른 날 제안 옴) | `/projects/{id}/visits` | `/projects/{id}/visits` | 같은 파일(상태판) | B2 | 같음 | GET /projects/{id}/visits |
| C21 | `pick_prop` | 제안한 날 고르기 (웹 짝 d_pick_prop) | `/projects/{id}/visits · 제안 날` | `/projects/{id}/visits/[visitId] · 제안 날` | 같은 파일 | B2 | 폰 / 웹: D17 달력 + 오른쪽 제안 칸 | POST …/proposal/pick · …/repick |
| C22 | `nooverlap` | 겹치는 날 없음 | `/projects/{id}/visits · 날짜 고르기` | `/projects/{id}/visits/[visitId] · 겹침 없음` | 같은 파일 | B2 | 같음(길 3개) | GET /projects/{id}/visits/{vid} |
| C23 | `chat_empty` | 채팅 (실측 확정 전) | `/chat · 빈 상태` | `/chat · 빈 상태` | app/chat/page.tsx (새) | B2 | 같음 | GET /threads |
| C24 | `chat_list` | 채팅 목록 (웹 짝 d_chat) | `/chat` | `/chat` | app/chat/layout.tsx · page.tsx (새) | B2 | 폰: 목록 화면 / 웹: D05 왼쪽 목록(대화가 오른쪽) | GET /threads · GET /stream |
| C25 | `chat` | 대화 | `/chat/{threadId}` | `/chat/[threadId]` | app/chat/[threadId]/page.tsx (새) · components/thread/* (새) | B2 | 폰: 전체 화면 / 웹: D05 오른쪽 칸 | GET /threads/{tid} · …/messages · POST …/messages · …/read |
| C26 | `plus` | + 메뉴 | `/chat/{threadId} · + 메뉴` | `/chat/[threadId] · + 메뉴` | components/thread/PlusMenu.tsx (새) | B2 | 같음(사진 · 실측 일정) | POST /files(chat_photo) |
| C28 | `change` | 일정 바꾸기 요청 카드 | `/chat/{threadId} · 요청 카드` | `/chat/[threadId] · 요청 카드` | components/thread/ChangeCard.tsx (새) | B2 | 같음 | POST /projects/{id}/visits/{vid}/changes · …/withdraw |
| C29 | `more` | ⋯ 메뉴 | `/chat/{threadId} · ⋯ 메뉴` | `/chat/[threadId] · ⋯ 메뉴` | components/thread/MoreMenu.tsx (새) | B2 | 같음 | 없음(메뉴) |
| C30 | `cancel` | 실측 취소 이유 | `/chat/{threadId} · 시트` | `/chat/[threadId] · 시트` | components/visit/CancelSheet.tsx (새, 실측 일정과 같이) | B2 | 폰 시트 / 웹 가운데 창 | POST /projects/{id}/visits/{vid}/cancel |
| C31 | `report` | 신고 · 차단 | `/chat/{threadId} · 시트` | `/chat/[threadId] · 시트` | components/report/ReportSheet.tsx (새, 업체 상세와 같이) | B2 | 폰 시트 / 웹 가운데 창 | POST /reports |
| C32 | `visited` | 실측 받으셨어요? | `/projects/{id}/visits` | `/projects/{id}/visits · 카드` | 같은 파일(상태판) | B2 | 같음 | POST /projects/{id}/visits/{vid}/visited |
| C33 | `compare` | 실측 견적서 비교 (웹 짝 d_compare) | `/projects/{id}/quotes` | `/projects/{id}/quotes` | app/projects/[id]/quotes/page.tsx (고침) | B2 | 폰: 업체 카드 / 웹: D18 비교표 | GET /projects/{id}/quotes · POST /projects/{id}/visits/{vid}/requote |
| C34 | `confirm` | 업체 확정 (확인 창) | `/projects/{id}/quotes/{visitId}/confirm` | `/projects/{id}/quotes/[visitId]/confirm` | app/projects/[id]/quotes/[visitId]/confirm/page.tsx (고침) | B2 | 폰 화면 / 웹 가운데 창 모양 | POST /projects/{id}/quotes/{visit}/confirm |
| C35 | `dates` | 공사 날짜 수락 | `/projects/{id}/schedule` | `/projects/{id}/schedule` | app/projects/[id]/schedule/page.tsx (고침) | B2 | 같음(날 하나씩 표시) | GET /projects/{id}/schedule · POST …/dates/{pid}/accept |
| C36 | `plan1` | 확정 공정표 (웹 짝 d_plan1) | `/projects/{id}/plan` | `/projects/{id}/plan · 확정` | app/projects/[id]/plan/page.tsx (고침) | B2 | 폰: 날마다 오전 · 오후 / 웹: D19 반나절 표 + 오른쪽 공사 전 할 일 | GET /projects/{id}/plan · GET /projects/{id}/plan.ics |
| C37 | `extra` | 추가 금액 확인 | `/projects/{id}/schedule · 추가 금액` | `/projects/{id}/schedule · 추가 금액` | components/schedule/ExtraAnswer.tsx (고침) | B2 | 같음 | POST /projects/{id}/deals/{did}/extras/{eid}/answer |
| C38 | `done_ok` | 공사 끝 확인 | `/projects/{id}/schedule · 공사 끝` | `/projects/{id}/schedule · 공사 끝` | components/schedule/DoneCheck.tsx (고침) | B2 | 같음 | POST /projects/{id}/deals/{did}/check |
| C39 | `review` | 리뷰 쓰기 | `/projects/{id}/review (새로)` | `/projects/{id}/review` | app/projects/[id]/review/page.tsx (새) | B2 | 같음 | POST /files(review_photo) · POST /projects/{id}/deals/{did}/review |
| C40 | `home1` | 홈 (로그인 뒤) (웹 짝 d_home) | `/ · 로그인 뒤` | `/ (로그인 뒤)` | app/page.tsx (고침) | B2 | 폰: 아래 탭 바 + 진행 중 띠 / 웹: 머리 아래 진행 중 띠 | GET /projects |
| C41 | `resume` | 이어 하기 / 새 집 | `/ · 확인 창` | `/ · 확인 창` | components/home/ResumeDialog.tsx (새) | B2 | 폰 시트 / 웹 가운데 창 | GET /projects |
| C42 | `my` | 내 공사 (웹 짝 d_my) | `/my` | `/my` | app/my/page.tsx (고침) | B2 | 폰: 카드 + 단계 띠 6칸 / 웹: D09 + 머리 알림 펼침 | GET /projects |
| C43 | `project` | 한 공사 화면 | `/projects/{id}` | `/projects/{id}` | app/projects/[id]/page.tsx (고침) | B2 | 폰: 요약 · 기록 탭 / 웹: 공사 띠 + 같은 탭 | GET /projects/{id}/overview |
| C44 | `notif` | 알림 | `/notifications` | `/notifications` | app/notifications/page.tsx (고침) | B2 | 폰 화면 / 웹 머리 펼침(D09)과 같은 목록 | GET /notifications · POST …/read · read-all |
| C45 | `account` | 내 정보 | `/account` | `/account` | app/account/page.tsx (고침) | B2 | 같음 | GET /me |
| C46 | `reset` | 비밀번호 찾기 | `/reset-password` | `/reset-password` | app/reset-password/page.tsx | B2 | 같음(메일은 팀 확인 12) | 없음(화면만) |
| C47 | `photo_view` | 시공 사례 크게 보기 | `/projects/{id}/vendors/{vid} · 사진` | `/projects/{id}/vendors/[vid]` · `?photo=n` | components/vendors/PhotoViewer.tsx (새) | B2 | 폰: 옆으로 넘김 / 웹: 가운데 창 | GET /projects/{id}/vendors/{vid}/photos/{file} |
| C48 | `reviews` | 리뷰 전체 | `/projects/{id}/vendors/{vid} · 리뷰` | `/projects/{id}/vendors/[vid]/reviews` | app/projects/[id]/vendors/[vid]/reviews/page.tsx (새) | B2 | 같음(최신순 · 낮은 별점부터) | GET /projects/{id}/vendors/{vid}/reviews · POST /reports(link) |
| C49 | `review_rules` | 리뷰 기준 | `/projects/{id}/vendors/{vid} · 시트` | `리뷰 화면 · 시트` | components/review/RulesSheet.tsx (새) | B2 | 폰 시트 / 웹 가운데 창 | 없음(정적 글, 법무) |
| C50 | `info_locked` | 기본 정보 (요청 뒤 잠김) | `/start · 잠김` | `/start?edit=[id] · 잠김` | app/start/page.tsx (고침) | B2 | 같음 | GET /projects/{id} |
| C51 | `phone` | 휴대폰 번호 넣기 | `/account · 휴대폰` | `/account/phone` | app/account/phone/page.tsx (새, 지금 /signup/phone 옮김) | B2 | 같음(인증 문자는 팀 확인 12) | PATCH /me |
| C52 | `dates_req` | 공사 다른 날짜 요청 | `/projects/{id}/schedule · 시트` | `/projects/{id}/schedule · 시트` | components/schedule/DateRequestSheet.tsx (고침) | B2 | 폰 시트 / 웹 가운데 창 | POST /projects/{id}/deals/{did}/date-requests |
| C53 | `withdraw` | 탈퇴 | `/account · 시트` | `/account · 시트` | components/my/WithdrawSheet.tsx (고침) | B2 | 폰 시트 / 웹 가운데 창 | POST /me/withdraw |
| C54 | `faq` | 자주 묻는 질문 | `/faq` | `/faq` | app/faq/page.tsx | B2 | 같음 | 없음(정적 글) |
| C55 | `legal` | 약관 · 개인정보 처리방침 | `/legal` | `/legal` | app/legal/page.tsx | B2 | 같음 | 없음(법무 글) |
| C56 | `notfound` | 찾을 수 없음 · 오류 | `not-found · error` | `not-found · error` | app/not-found.tsx · app/error.tsx | B2 | 같음(남의 공사도 같은 화면) | 없음 |
| C57 | `std_guest` | 표준견적서 (로그인 전) (웹 짝 d_std_guest) | `/start/standard` | `/start/standard` | app/start/standard/page.tsx (새) | B2 | 폰: 머리 'AI에게 묻기'(칩만) / 웹: D12 옆 칸(칩만) | POST /guest/standard |
| C58 | `ai_guest` | 로그인 전 AI에게 묻기 (웹 짝 d_std_guest) | `/start/standard · 시트` | `/start/standard · 시트` | components/ai/GuestAsk.tsx (새) | B5 | 폰 시트 / 웹 옆 칸 | 없음(자주 묻는 질문 칩) |
| C59 | `join` | 가입 · 로그인 카드 (가운데) (웹 짝 d_join) | `/start/standard · 확인 창` | `/start/standard · 확인 창` | components/auth/JoinDialog.tsx (새) | B2 | 폰 · 웹 가운데 카드(D13) | 없음 → /signup |
| C60 | `std_part` | 표준견적서 · 부분 공사 (예시) | `/projects/{id}/standard · 부분` | `/projects/{id}/standard · 부분` | 같은 파일 | B2 | 같음('부분 · 실측 후 확정') | GET /projects/{id}/standard |
| C61 | `pick_ok` | 이 날짜로 확정 (확인 창) | `/projects/{id}/visits · 확인 창` | `/projects/{id}/visits/[visitId] · 확인 창` | components/visit/ConfirmPick.tsx (새) | B2 | 폰 시트 / 웹 가운데 창(I5) | POST /projects/{id}/visits/{vid}/pick |
| C62 | `chat_warn` | 대화 · 믿집 밖 거래 주의 줄 | `/chat/{threadId} · 주의` | `/chat/[threadId] · 주의 줄` | components/thread/WarnLine.tsx (새) | B2 | 같음(고객 화면만) | GET …/messages(warn) |
| C63 | `project_log` | 한 공사 화면 · 기록 탭 | `/projects/{id} · 기록` | `/projects/{id}?tab=log` | 같은 파일 | B2 | 같음 | GET /projects/{id}/log |
| D01 | `d_std` | 표준견적서 + AI 칸 (데스크톱) | `/projects/{id}/standard` | `/projects/{id}/standard` | C07과 같은 파일 | B2 · B5 | 웹 배치(공사 띠 + 옆 AI 칸) | GET /projects/{id}/standard · POST /ai/turns |
| D02 | `d_price` | 도배 단가 (업체 데스크톱) | `/vendor/prices/dobae` | `/vendor/prices/dobae` | app/vendor/prices/[trade]/page.tsx (새, 지금 profile 안 PriceSection 옮김) | B3 | 웹: 표 / 폰: 같은 줄을 카드로 | GET /vendor/prices · POST /vendor/prices/{trade}/confirm |
| D03 | `d_visit` | 실측 일정 + AI 칸 (데스크톱) | `/projects/{id}/visits` | `/projects/{id}/visits` | C14와 같은 파일 | B2 · B5 | 웹 비교표(W4 A) + 공사 띠 '지금 할 일 ▾' | GET /projects/{id}/visits |
| D04 | `d_inbox` | 업체 작업함 (데스크톱 표) | `/vendor` | `/vendor` | app/vendor/page.tsx (고침) · components/pro/inbox/* (고침) | B3 | 웹: 표 + 줄 누르면 옆 자세히(N4 C 아이콘 + 글자) | GET /vendor/visits?tab= · summary |
| D05 | `d_chat` | 채팅 2단 (데스크톱 · 실측 뒤) | `/chat/{threadId}` | `/chat/[threadId]` | C25와 같은 파일 + app/chat/layout.tsx | B2 | 웹 2단(목록 + 대화) | GET /threads · …/messages |
| D06 | `d_vendors` | 업체 보기 + AI 칸 (데스크톱) | `/projects/{id}/vendors` | `/projects/{id}/vendors` | C10과 같은 파일 | B2 · B5 | 웹 배치 | GET /projects/{id}/vendors |
| D07 | `d_vdetail` | 업체 상세 + AI 칸 (데스크톱) | `/projects/{id}/vendors/{vid}` | `/projects/{id}/vendors/[vid]` | C11과 같은 파일 | B2 · B5 | 웹 배치(가견적 표 · 합지로 보기) | GET /projects/{id}/vendors/{vid}?grade= |
| D08 | `d_req` | 실측 일정 요청서 + AI 칸 (데스크톱) | `/projects/{id}/visits · 요청서` | `/projects/{id}/visits/new` | C13과 같은 파일 | B2 · B5 | 웹 배치(끌어다 놓기 · AI 초안 카드) | GET /projects/{id}/visits/draft · POST /projects/{id}/visits |
| D09 | `d_my` | 내 공사 + 알림 펼침 (데스크톱) | `/my` | `/my` | C42와 같은 파일 + components/site 알림 펼침(B4) | B2 · B4 | 웹 배치 | GET /projects · GET /notifications |
| D10 | `d_home` | 홈 (데스크톱 · 로그인 전) | `/ · 로그인 전` | `/` | C01과 같은 파일 | B2 | 웹 배치(이렇게 진행돼요 6단계) | POST /guest/standard(견본) |
| D11 | `d_info` | 기본 정보 (데스크톱) | `/start` | `/start` | C02와 같은 파일 | B2 | 웹 배치(오른쪽 요약) | GET /regions … |
| D12 | `d_std_guest` | 표준견적서 + 로그인 전 AI 칸 (데스크톱) | `/start/standard` | `/start/standard` | C57과 같은 파일 | B2 · B5 | 웹 배치(옆 칸은 칩만) | POST /guest/standard |
| D13 | `d_join` | 가입 · 로그인 카드 (데스크톱 가운데) | `/start/standard · 확인 창` | `/start/standard · 확인 창` | C59와 같은 파일 | B2 | 웹 가운데 카드 | 없음 |
| D14 | `d_period` | 기간 답하기 (업체 데스크톱) | `/vendor/requests/{id}` | `/vendor/requests/[visitId]` | V04와 같은 파일 | B3 | 웹: 요청 내용 + 큰 달력 + 이미 잡힌 실측 | GET /vendor/visits/{vid} · POST …/window |
| D15 | `d_pick_on` | 날짜 고르기 · 바로 확정 (데스크톱) | `/projects/{id}/visits · 날짜 고르기` | `/projects/{id}/visits/[visitId]` | C16과 같은 파일 | B2 · B5 | 웹 배치 | POST /projects/{id}/visits/{vid}/pick |
| D16 | `d_pick_off` | 날짜 고르기 · 업체가 수락 (데스크톱) | `/projects/{id}/visits · 날짜 고르기` | `/projects/{id}/visits/[visitId]` | C19와 같은 파일 | B2 · B5 | 웹 배치 | POST /projects/{id}/visits/{vid}/pick |
| D17 | `d_pick_prop` | 제안한 날 고르기 (데스크톱) | `/projects/{id}/visits · 제안 날` | `/projects/{id}/visits/[visitId]` | C21과 같은 파일 | B2 · B5 | 웹 배치 | POST …/proposal/pick |
| D18 | `d_compare` | 실측 견적서 비교 (데스크톱) | `/projects/{id}/quotes` | `/projects/{id}/quotes` | C33과 같은 파일 | B2 · B5 | 웹 비교표 | GET /projects/{id}/quotes |
| D19 | `d_plan1` | 확정 공정표 (데스크톱) | `/projects/{id}/plan` | `/projects/{id}/plan` | C36과 같은 파일 | B2 · B5 | 웹 반나절 표 | GET /projects/{id}/plan · plan.ics |
| V01 | `v_signup` | 업체 가입 신청 | `/signup/vendor` | `/signup/vendor` | app/signup/vendor/page.tsx (고침) · components/auth/VendorSignupForm* (고침) | B3 | 폰: 눌러서 고르기 / 웹: 끌어다 놓기(I9) | POST /files(license) · POST /auth/vendor-signup |
| V02 | `v_first` | 승인 · 처음 할 일 | `/vendor · 승인 뒤` | `/vendor · 승인 뒤` | app/vendor/page.tsx · components/pro/home/FirstDay.tsx (고침) | B3 | 같음(할 일 4줄) | GET /vendor/application · GET /vendor/prices |
| V03 | `v_inbox` | 작업함 · 할 일 (웹 짝 d_inbox) | `/vendor` | `/vendor` | app/vendor/page.tsx (고침) | B3 | 폰: 탭 5개 + 카드(N4 C) / 웹: D04 표 | GET /vendor/visits?tab= · summary |
| V04 | `v_period` | 기간 답하기 (웹 짝 d_period) | `/vendor/requests/{id}` | `/vendor/requests/[visitId]` | app/vendor/requests/[visitId]/page.tsx (고침) | B3 | 폰: 달력 + 토글 / 웹: D14 | GET /vendor/visits/{vid} · POST …/window |
| V05 | `v_decline` | 못 받아요 · 이유 | `/vendor/requests/{id} · 시트` | `/vendor/requests/[visitId] · 시트` | components/pro/inbox/DeclineButton.tsx (고침) | B3 | 폰 시트 / 웹 가운데 창 | POST /vendor/visits/{vid}/decline |
| V06 | `v_accept` | 날짜 수락 | `/vendor/requests/{id}` | `/vendor/requests/[visitId] · 수락` | 같은 파일(상태별) | B3 | 같음 | POST /vendor/visits/{vid}/accept |
| V07 | `v_propose` | 다른 날 제안 | `/vendor/requests/{id} · 다른 날 제안` | `/vendor/requests/[visitId]?step=propose` | components/pro/visit/ProposeForm.tsx (새) | B3 | 같음(반나절 3개까지) | POST /vendor/visits/{vid}/propose |
| V08 | `v_sched` | 작업함 · 일정 탭 | `/vendor · 일정` | `/vendor?tab=sched` | components/pro/inbox/Schedule.tsx (새) | B3 | 폰: 오늘 · 내일 · 이번 주 / 웹: 표 안 탭 | GET /vendor/schedule |
| V09 | `v_chat` | 업체 채팅 (고객이 동 · 호를 알려 줌) | `/chat/{threadId} · 업체` | `/chat/[threadId] · 업체` | C25와 같은 파일(역할로 나눔) | B2 | 업체는 '상계동 고객'으로 봐요 | GET /threads/{tid} · …/messages |
| V10 | `v_quote` | 실측 견적서 올리기 | `/vendor/requests/{id}/quote` | `/vendor/requests/[visitId]/quote` | app/vendor/requests/[visitId]/quote/page.tsx (고침) | B3 | 폰: 눌러서 고르기 / 웹: 끌어다 놓기 | GET · PUT /vendor/visits/{vid}/quote · POST …/send · POST /files(quote_doc) |
| V11 | `v_dates` | 공사 날짜 올리기 | `/vendor/jobs/{dealId}` | `/vendor/jobs/[dealId] · 공사 날짜` | app/vendor/jobs/[dealId]/page.tsx (고침) | B3 | 같음(날 하나씩) | GET /vendor/jobs/{did} · …/dates/preview · POST …/dates |
| V12 | `v_extra` | 추가 금액 올리기 | `/vendor/jobs/{dealId} · 추가 금액` | `/vendor/jobs/[dealId] · 시트` | components/pro/jobs/JobExtras.tsx (고침) | B3 | 폰 시트 / 웹 가운데 창 | POST /files(work_photo) · POST /vendor/jobs/{did}/extras |
| V13 | `v_done` | 공사 끝냈어요 | `/vendor/jobs/{dealId} · 공사 끝` | `/vendor/jobs/[dealId] · 시트` | components/pro/jobs/JobFinish.tsx (고침) | B3 | 폰 시트 / 웹 가운데 창 | POST /files(done_photo) · POST /vendor/jobs/{did}/done |
| V14 | `v_needinfo` | 심사 보완 요청 | `/vendor · 보완` | `/vendor · 보완` | components/pro/home/ResubmitForm.tsx (고침) | B3 | 같음 | GET /vendor/application · POST …/resubmit |
| V15 | `v_profile` | 업체 정보 · 기본 | `/vendor/profile` | `/vendor/profile` | app/vendor/profile/page.tsx (고침) | B3 | 같음(탭: 기본 · 사례 · 링크) | GET · PUT /vendor/profile |
| V16 | `v_cases` | 업체 정보 · 시공 사례 | `/vendor/profile · 사례` | `/vendor/profile?tab=cases` | components/pro/profile/Cases.tsx (새) | B3 | 폰: 눌러서 고르기 / 웹: 끌어다 놓기 | POST · DELETE /vendor/portfolio |
| V18 | `v_links` | 업체 정보 · 링크 | `/vendor/profile · 링크` | `/vendor/profile?tab=links` | components/pro/profile/Links.tsx (새) | B3 | 같음 | GET · PUT /vendor/review-links · PUT /vendor/profile(사례 링크) |
| V19 | `v_chats` | 업체 채팅 목록 | `/chat · 업체` | `/chat · 업체` | C24와 같은 파일 | B2 | 같음(동네로 보임) | GET /threads |
| V20 | `v_change` | 일정 바꾸기 요청 받기 | `/chat/{threadId} · 업체` | `/chat/[threadId] · 업체 카드` | components/thread/ChangeCard.tsx(업체 단추) | B2 | 같음 | POST /vendor/visits/{vid}/changes/{cid}/accept · …/propose |
| V21 | `v_notif` | 업체 알림 | `/notifications · 업체` | `/notifications · 업체` | C44와 같은 파일 | B2 | 같음 | GET /notifications |
| V22 | `v_rejected` | 가입 거절 · 다시 신청 (예시) | `/vendor · 거절` | `/vendor · 거절` | components/pro/home/ApplicationHome.tsx (고침) | B3 | 같음(사유 코드 + 다시 신청) | GET /vendor/application · POST …/reapply |
| V23 | `v_job` | 공사 한 건 | `/vendor/jobs/{dealId}` | `/vendor/jobs/[dealId]` | app/vendor/jobs/[dealId]/page.tsx (고침) · components/pro/jobs/JobPage.tsx | B3 | 같음(공사 한 건) | GET /vendor/jobs/{did} · GET …/log |
| V24 | `v_reviews` | 업체 리뷰 · 답글 | `/vendor/reviews` | `/vendor/reviews` | app/vendor/reviews/page.tsx (새) | B3 | 같음 | GET /vendor/reviews |
| V25 | `v_reply` | 답글 쓰기 | `/vendor/reviews · 시트` | `/vendor/reviews · 시트` | components/pro/reviews/ReplySheet.tsx (새) | B3 | 폰 시트 / 웹 가운데 창 | PUT /vendor/reviews/{rid}/reply |
| A01 | `a_review` | 업체 심사 (관리자) | `/admin/vendors` | `/admin/vendors` | app/admin/vendors/page.tsx (고침) | B3 | 웹 전용. 표 + 오른쪽 자세히(등록증 · 같은 상호 · 외부 리뷰 링크) | GET /admin/vendors · /admin/vendors/{id} · POST …/review · …/links/{sort} |
| A02 | `a_report` | 신고 · 링크 처리 (관리자) | `/admin/reports (새로)` | `/admin/reports` | app/admin/reports/page.tsx (새) | B3 | 웹 전용. 탭(처리 기다림 · 처리함) + 종류 거르기 + 자세히 | GET /admin/reports · /admin/reports/{id} · POST …/resolve |
| A03 | `a_members` | 회원 관리 (관리자) | `/admin/members` | `/admin/members` | app/admin/members/page.tsx (고침: 예시 데이터 → API) | B3 | 웹 전용. 줄 안에서 한 번 더 묻기 | GET /admin/members · POST …/{uid}/suspend · unsuspend |
| A04 | `a_reject` | 업체 거절 · 이유 (관리자) | `/admin/vendors · 확인 창` | `/admin/vendors · 확인 창` | components/admin/RejectDialog.tsx (새) | B3 | 가운데 창(사유 코드 4개 + 메모) | POST /admin/vendors/{id}/review |

## 3. 화면 묶음이 같이 쓰는 조각

| 조각 | 위치 | 주인 | 쓰는 화면 |
| --- | --- | --- | --- |
| 껍데기(머리 · 아래 탭 바 · 공사 띠 · 알림 펼침) | `components/site/*` | B4 | 거의 모두 |
| 실시간 한 줄기(`LiveProvider` · `useLive`) | `lib/backend/stream.ts` · `components/site/LiveProvider.tsx` | B2(stream) · B4(자리) | 머리 알림 수 · 채팅 · 실측 일정 · 작업함 |
| 달력(반나절 · 기간 · 날 하나씩) | `components/ui/Calendar*` | B4 | C13 · C16 · C19 · C21 · C28 · C35 · C52 · V04 · V07 · V11 · D14~D17 |
| 확인 창 · 시트 | `components/ui/Dialog` · `Sheet` | B4 | 확인 창 · 시트 표시 화면 전부 |
| 끌어다 놓기 · 눌러서 고르기 | `components/ui/FileDrop` | B4 | C13 · C26 · C39 · V01 · V10 · V12 · V13 · V14 · V16 |
| '믿집 계산' 상자 · 금액 표시 | `components/ui/CalcBox` · `lib/format.ts` | B4 | AI 칸 · 표준견적서 · 가견적 · 비교 |
| 상태 아이콘 + 글자(N4 C) | `components/ui/StateTag` | B4 | V03 · V08 · D04 · C14 · D03 |
| 신고 창 | `components/report/ReportSheet` | B2 | C11 · C31 · C48(링크) — 업체 화면(B3)도 가져다 써요 |
| 채팅 | `components/thread/*` | B2 | C23~C31 · C62 · D05 · V09 · V19 · V20 |
| AI 칸 | `components/ai/*` | B5 | C09 · C58 · D01 · D03 · D06~D08 · D12 · D15~D19 |

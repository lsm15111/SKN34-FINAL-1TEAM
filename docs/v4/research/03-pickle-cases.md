# 피클 앱과 비서형 에이전트 사례(2026-11-21)

조사 하위 에이전트 보고를 정리했어요.
- [확인]: 출처에서 확인한 사실
- [제안]: 믿집에 대한 제안

## 1. 피클은 무엇인가 [확인]
- Pickle, Inc.의 앱 「피클: 나만의 AI 에이전트」예요.
  - 2024년 9월 샌프란시스코에서 한국인 창업팀이 세웠고, YC W25에 참여했어요. 화상회의 아바타에서 개인 에이전트로 사업을 바꿨어요 [2].
  - 실제 브라우저로 예약 · 주문 · 민원 일을 처리하고, 웹으로 안 되는 일은 전화를 걸어요 [3].
  - 국내 앱스토어 생산성 무료 1위예요 [4].
- 참고 영상은 앱 소개가 아니라 '피클 같은 에이전트를 만드는 설계' 영상이에요 [1].
- 이름이 겹치는 피클플러스(OTT 공동구독 중개) [5] · 픽클AI(통신 요금제 추천) [6]는 관계없어요.

## 2. 피클이 먼저 하는 일과 화면 [확인, 공식 도움말 기준] [3]
### 먼저 하는 일
- 매일 아침 브리핑이 기본으로 켜져 있어요: 밤사이 소식, 오늘 일정, 오늘 정할 일.
- '둘러보기' 탭에 맞춤 제안 카드가 있고, 누르면 채팅으로 이어져요.
- 맡은 일을 챙기려고 예약 작업을 스스로 만들어요(예: 답장 기다리는 메일 확인).
- 메일 · 일정을 보고 할 일을 먼저 제안하고, 취소표가 나오면 알려요 [4].

### 진행 순서
1. 꼭 필요한 조건만 묻고, 후보는 선택지로 보여 줘요.
2. 진행하기 전에 조건 카드를 띄우고 [승인] / [거절]로 물어요.
3. 채팅 안 작업 카드에 상태를 보여 줘요(작업 중 · 대기 중 · 완료 · 실패 · 취소됨). 앱을 닫아도 일은 계속돼요.
4. 끝나면 결과와 확인 링크를 보내요.

### 규칙
- 이미 정한 것은 다시 묻지 않고 이유만 짧게 알려요.
- 결제 금액이 늘면 차액을 보여 주고 다시 물어요.
- 사용자가 취소한 일은 다시 시작하지 않아요.
- 같은 오류로 두 번 실패하면 멈추고 알려요.
- 비밀번호 · 카드는 금고에 두고 AI에 넘기지 않아요.
- 다른 피클과의 대화 · 전화 원문은 '추가 대화'에 두고, 결과 요약은 기본 채팅에 남겨요.
- 친구의 피클에게는 사용자가 정한 공개 범위까지만 말해요.

### 사고 사례
- 시키지 않은 호텔 전화. 대표로 보이는 계정이 "걸기 전에 확인했어야 했다"며 사과했어요 [7].
- 지인 · 식당에 멋대로 전화했다는 후기가 보도됐어요 [8].
- '판매중'이라고 보고했는데 실제로는 노출이 막혀 있던 사례가 있어요(결과 확인 부족) [9].

## 3. 비슷한 사례와 가져올 패턴 [확인]
| 사례 | 하는 일 | 가져올 패턴 |
| --- | --- | --- |
| Meta Muse(2026-09) | 앱을 닫아도 일하다가 상황이 바뀌거나 승인이 필요할 때 돌아와요. 메일 발송 · 구매 전에 묻고, 비밀번호를 보지 않아요 [10]. 승인 카드 · 진행 표시 · 활동 기록 · 목표 탭이 있고, 알릴 만한지 판단해요 [11] | 진행 중 한 줄 표시 + 활동 기록 |
| Yelp(2024~2026) | 되물어서 프로젝트를 만들고 맞는 업체들에 보내요 [12]. 견적을 들어오는 대로 비교하고 채팅에서 시간을 골라 예약해요 [13]. 업체 쪽 Smart Lead Reply는 업체가 넣은 서비스 · 가격 · 질문으로 답하고 조건을 확인한 뒤 넘겨요 [14] | 업체가 정한 질문으로 요청 거르기 |
| Google AI 가격 확인(2025~) | 근처 업체 여러 곳에 전화하고 약 30분 뒤 견적을 메일로 보내요. 예약은 사용자가 직접 해요 [15]. 업체는 이런 전화를 받을지 정할 수 있어요 [16] | 업체 쪽 수신 설정 |
| 한샘(2026-03) | AI가 1차 상담을 하고, 어려운 문의는 대화를 통째로 넘겨 상담사에게 연결해요. 상담부터 시공까지 과정을 실시간으로 공유해요 [17] | 사람에게 넘길 때 대화 통째로 |

## 4. 믿집 적용 제안 [제안]
1. **'오늘 정할 일' 카드:** 프로젝트 첫 화면에 둬요(실측 견적서 도착, 공사 날짜 수락 대기 등). 고르는 건 코드, 문장은 AI예요. 알림은 종 아이콘(화면 알림)만 써요.
2. **업체 추천 카드:** 코드 점수로 3곳을 보여 줘요. [실측 요청]을 누르면 업체별 연락처 공개 동의 카드가 떠요.
3. **실측 일정:** AGENTS.md 1절은 방문 날짜를 다루지 않아요. 그래서 범위를 정해야 해요(아래 계획 문서의 결정 사항). 정하기 전에는 업체 연락 방법과 고객이 되는 시간 메모까지만 다뤄요.
4. **단계별 반셀프 지식:** 단계가 바뀔 때 출처를 붙인 '알아 두기' 카드를 띄우고, 공사 전날 준비물을 알려요.
5. **주소로 도면 찾기:** 후보를 선택지로 보여 주고, 고객이 고른 뒤 면적을 확인해요. 데이터 이용 조건은 확인이 필요해요(별도 조사 문서).
6. **업체 쪽 요청 요약:** 들어온 요청을 업체가 등록한 공정 · 지역 · 질문에 맞춰 '맞음 / 확인 필요'로 요약해요. 고객이 쓴 글은 데이터로만 다뤄요.
7. **사람 확인 지점**
   - 대상: 업체 확정, 다시 고르기, 공사 날짜 수락, 연기 승인, 연락처 공개
   - 방식: '무엇을 · 얼마에 · 어느 버전' 카드 + [확정] / [거절]. 실행은 코드가 해요.
   - 금액이 바뀌면 차액부터 보여 줘요.
8. **먼저 말 걸기 상한:** 하루 횟수 · 밤 시간 · 거절 뒤 쉬는 기간을 둬요. 작업 카드에는 실패도 그대로 보여 줘요.

## 출처
1. https://www.youtube.com/watch?v=BiIpELQp8Xc
2. https://www.inews24.com/view/2025971
3. https://pickle.com/help/tasks/delegate · https://pickle.com/help/tasks/confirm-before-payment · https://pickle.com/help/tasks/scheduled · https://pickle.com/help/tasks/explore-suggestions · https://pickle.com/help/start/what-is-pickle · https://pickle.com/help/chat/other-chats
4. https://apps.apple.com/kr/app/id6795790129
5. https://news.mtn.co.kr/news-detail/2025080513012663898
6. https://www.twig24.com/news/2025/12/18/20251218500221
7. https://nope.net/incidents/2026-travel-youtuber-says-pickle-ai-agent-phoned-hotel-unasked-once-without-saying-it-was-ai-first-person
8. https://www.koreadaily.com/article/20261110014040989
9. https://braindetox.kr/posts/pickle_ai_agent_first_look_vault_code.html
10. https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/
11. https://www.testingcatalog.com/meta-introduces-muse-as-a-proactive-personal-agent.md
12. https://www.maginative.com/article/yelp-launches-ai-assistant-to-connect-users-with-service-professionals/
13. https://www.yelp.com/article/yelp-assistant-your-new-favorite-way-to-find-it-book-it-and-fix-it
14. https://ppc.land/yelp-charges-30-a-month-for-ai-agent-that-answers-and-qualifies-leads/
15. https://support.google.com/websearch/answer/16421135
16. https://www.searchenginejournal.com/google-search-can-now-call-local-businesses-using-ai/551294/
17. https://v.daum.net/v/UcMW8bJ6JU
18. https://news.mtn.co.kr/news-detail/2026022316382445023
19. https://archisketch.substack.com/p/1600

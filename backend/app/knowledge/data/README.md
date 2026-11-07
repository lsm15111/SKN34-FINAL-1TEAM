# 지식 데이터 (원본)

에이전트 · 선제 안내 카드가 쓰는 지식의 원본이다. PR로 고치고, `python -m app.knowledge.ingest`로 검사한 뒤 적재한다. 형식은 [docs/agent/04-knowledge.md](../../../../docs/agent/04-knowledge.md) 4절.

| 파일 | 내용 | 줄 하나 |
| --- | --- | --- |
| `sources.jsonl` | 출처(법령 · 시방서 · 제조사 · 기사 · 커뮤니티)와 신뢰도 · 이용 조건 | `{"key":"S-T1-46", "title", "url", "reliability", "rag_policy", ...}` |
| `cards.jsonl` | 선제 안내 카드. 코드 트리거가 골라 화면에 보인다 | `{"key":"dobae.silk_no_overlay", "phase":"P1", "stage", "level", "why", "title", "body", "trigger", "priority", "sources"}` |
| `terms.jsonl` | 용어집(현장어 별칭 포함) | `{"term", "aliases", "easy", "detail", "trade", "sources"}` |
| `chunks.jsonl` | 검색(RAG) 조각. 자체 요약만 | `{"key", "kind", "trade", "stage", "level", "title", "body", "sources", "conflict", "valid_to"}` |
| `lexicon.jsonl` | 고객 표현 → 옵션 후보 · 되물을 것 · 연계 공정 플래그 | `{"phrase", "variants", "intent", "options", "ask", "flags", "confidence", "sources"}` |

## 지켜야 할 것

- **지금 파일은 AI 초안이다**(조사 7갈래 → 데이터 작성 에이전트). 줄마다 `"reviewed": false`가 붙어 있다. 사람이 읽고 맞으면 `true`로 바꾼다. 적재는 처음에는 전부, 운영 전에는 `reviewed=true`만.
- 원문을 베끼지 않는다. 제조사 자료는 규격 · 인증 수치만(이용 조건), 업계 블로그 · 커뮤니티 수치는 범위 · 날짜와 함께.
- 출처끼리 값이 다르면 `conflict: true`이고 본문에 "자료마다 달라요"를 쓴다.
- 이 집의 견적 금액처럼 보이는 숫자를 쓰지 않는다(금액은 계산 엔진). 시세가 든 조각은 `valid_to`를 둔다.
- 화면에 보이는 글은 '-해요'체, 영어 상태값을 쓰지 않는다.
- 출처 키는 `S-T<트랙>-<출처 번호>`(조사 문서 [docs/research](../../../../docs/research/README.md)의 번호).

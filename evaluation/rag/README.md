# RAG 검색 평가

상담 근거 검색이 질문에 맞는 조각을 위쪽에 가져오는지 잰다. LLM 호출 없음(무료).

## 파일
- `questions.jsonl`: 평가 질문 90개 (도배 33 · 목공 33 · 공통 24, dev 60 · held-out 30)
  - `expect`: `answer` | `no_source`(가격 · 업체 추천 · 범위 밖처럼 자료로 답하면 안 되거나 자료가 없는 질문)
  - `gold`: 정답 조각 `{ref, grade, why}`. grade 2 = 직접 답, 1 = 부분 관련. 후보(여러 검색의 상위 15개 합집합) + 말뭉치 낱말 검색으로 사람 대신 판정해 넣었다
  - `from`: 질문 출처 (`book` 시공 안내서, `mokgong_qa:q-…` 팀 목공 고객 질문, `written` 직접 씀)
- `corpus.py`: 합친 말뭉치 만들기 (화면 자료 K1~ · 서버 자료 K2001~ · 로컬 추가 자료 K5001~). 결과는 `.cache/`(git 제외)
- `rank.mjs`: 화면 검색(`rag.ts`)으로 질문마다 순위 뽑기
- `metrics.py`: hit@1 · hit@5 · recall@5 · MRR · nDCG@5, 자료 없음 질문의 '자료 부족' 판단률

## 돌리기
```bash
python evaluation/rag/corpus.py
node evaluation/rag/rank.mjs --name current
python evaluation/rag/metrics.py evaluation/rag/.cache/rank_current.json
```
- held-out은 마지막에 한 번만: `--final`
- 로컬 추가 자료(책)가 없으면 K5001~ 정답은 찾을 수 없어 점수가 낮게 나온다. 책 조각이 있는 로컬에서 잰다

## 기준선 (2026-11-13, dev 58문항)
| 검색 | hit@1 | hit@5 | recall@5 | MRR | nDCG@5 |
|---|---|---|---|---|---|
| 화면 검색 (공정 자리 확보 전) | 0.345 | 0.586 | 0.284 | 0.629 | 0.352 |
| 화면 검색 (공정 자리 확보) | 0.414 | 0.603 | 0.304 | 0.669 | 0.398 |
- 공정별 hit@5 (자리 확보): 도배 0.429 · 목공 0.773 · 공통 0.600
- 자료 없음 질문 2개는 모두 '자료 충분'으로 판단(0/2)

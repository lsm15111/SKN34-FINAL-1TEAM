# 평가 세트 (초안)

지표 · 두 층(CI · 야간) · 파일 형식은 [docs/agent/09-eval.md](../docs/agent/09-eval.md)에 있다. 지금 파일은 **AI 초안**이라 줄마다 `"reviewed": false`가 붙어 있다. 사람이 확인하면 `true`로 바꾼다.

## 세트

| 폴더 | 파일 | 개수 | 출처 · 나누기 |
| --- | --- | ---: | --- |
| `intent/` | `dev` · `heldout` | 146 · 67 | 초보 질문 원형 Q001~Q213(docs/research/T7 2.2). 경로별로 id 순 정렬해 3번째마다 held-out(2.18:1) |
| `intent/` | `aug` | 60 | 반말 · 오타 · 줄임 · 평형 · 범위 · 천장 · 거주 슬롯을 바꾼 변형. `base_split`이 heldout인 16개는 **학습에 쓰지 않는다** |
| `guide/` | `dev` · `heldout` | 34 · 16 | 골든 요점 G1~G12 × 3문항 + 도배 · 목공 초보 질문(T2 · T3 9장). `must` · `must_not` 체크포인트 |
| `orchestrator/` | `dev` | 30 | 단일 · 두 공정 병렬 · 다중 경로 · 분해기 · 상한 초과 · 범위 밖 · 악용 · 간접 주입 · 되묻기 |
| `consult/` | `dev` | 10 | 도배 5 · 목공 5 다중 턴, 모든 대화에 "모르겠어요" 턴. `expect_slots`는 고객 확인 뒤 상태 |
| `rag/` | `dev` · `heldout` | 지식 조각과 함께 | 질의 → 관련 조각 key |

## 경로(12종)와 분포

| 경로 | dev | heldout | 합 |
| --- | ---: | ---: | ---: |
| coach | 50 | 25 | 75 |
| dobae | 20 | 9 | 29 |
| mokgong | 18 | 8 | 26 |
| estimate | 20 | 9 | 29 |
| schedule | 10 | 5 | 15 |
| abuse | 7 | 3 | 10 |
| oos_trade | 5 | 2 | 7 |
| chitchat | 4 | 2 | 6 |
| howto | 4 | 1 | 5 |
| oos_other | 3 | 1 | 4 |
| unclear | 3 | 1 | 4 |
| both | 2 | 1 | 3 |

- **both · unclear · oos_other가 3~4개뿐**이라 경로별 P/R이 흔들린다. 의도 200을 확정할 때 이 셋을 경로당 10개 이상으로 채운다.
- 경로 매기기 규칙: 공정 **사이** 순서 · 하자 · 분쟁 · 문구는 코치, 시공 중 확인이 한 공정에만 해당하면 그 공정, 두 공정의 작업 조건을 함께 묻으면 both. 화장실 문은 목공, 욕실 타일은 범위 밖, '도배 대신 페인트'는 도배.
- 첨부 견적서 속 숨은 지시(Q201)는 abuse가 아니라 estimate다. 관문은 사용자 문장만 분류하고, 숨은 지시는 데이터 블록 격리 · 출력 검사로 막는다(orchestrator O25에서 확인).

## 실행

```bash
python evaluation/run.py intent --pred preds.jsonl --split dev
python evaluation/run.py rag --pred ranked.jsonl --split heldout --k 5
```

결과는 `evaluation/results/<세트>-<split>-<날짜>.json`에 남는다.

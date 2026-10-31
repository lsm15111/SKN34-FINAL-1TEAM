# 도배 상담 비교 평가

'Claude에게 그냥 묻기'와 '믿집 도배 상담 에이전트'를 같은 모델 · 같은 사례로 비교한다.

- `cases.jsonl`: 사례 15개 (dev 10 · held-out 5). 고객 첫 말, 정답 카드(truth), 말한 칸(stated), 코드가 물어야 할 칸(ask)
- `run_compare.py`: 두 방식을 돌리고 코드로 채점한다. 결과는 `results/<날짜-시각>/`에 `raw.json`(원문)과 `summary.md`(표)로 남는다

```bash
cd backend
uv run python ../evaluation/dobae/run_compare.py            # 호출 수 · 예상 비용만
uv run python ../evaluation/dobae/run_compare.py --live     # 실제 호출 (유료, .env의 ANTHROPIC_API_KEY)
uv run python ../evaluation/dobae/run_compare.py --live --reuse-direct ../evaluation/dobae/results/<폴더>  # 우리 쪽만 다시
uv run python ../evaluation/dobae/run_compare.py --summary ../evaluation/dobae/results/<폴더>  # 표만 다시 (호출 없음)
```

## 결과 기록

| 폴더 | 상담 프롬프트 | 비고 |
| --- | --- | --- |
| `20261031-1645` | consult-v1 | 처음 전체 실행. 되물음 96% (d04 '천장도 해야 하나요?'를 모름으로 읽음) |
| `20261031-1649` | consult-v2 | 우리 쪽만 다시 실행, 그냥 묻기는 1645 결과를 씀. 되물음 100% |

## 두 방식

- 그냥 묻기: 시스템 프롬프트 없이 고객 말을 보낸다. 정보가 빠진 사례는 둘째 턴에 빠진 정보를 준다.
- 믿집 에이전트: 상담 API와 같은 흐름이다. 코드가 묻는 칸은 정답 카드로 답한다(버튼 클릭과 같음).

## 주의

- 그냥 묻기 답의 금액 · 되물음은 같은 모델이 effort low로 뽑는다. 판정이 아니라 추출이지만, 몇 건은 원문(`raw.json`)과 대조한다.
- '공공 기준과의 차이'는 오차가 아니다. 공공 기준은 비교 기준이고 업체 시세와 다를 수 있다.
- CI에서는 돌리지 않는다 (유료 호출 0회 규칙). 프롬프트를 바꾸면 이 결과를 다시 만들어 PR에 붙인다.

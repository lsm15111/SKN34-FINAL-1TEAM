# 공정 의견 평가 사례

공정 스펙(`app.consult.trades.REGISTRY`)으로 공정마다 약 5,000개를 만든다 (`make_cases.py`). 공정 키만 주면 되고,
도배 · 목공처럼 손볼 것이 있으면 `config.py`에 얇은 설정(규칙 덮어쓰기 · 더할 기대 · 손으로 쓴 모범 답)을 둔다.

- 범주 = 조건 없는 칸의 값 조합 (choice 값마다 · multi 조합마다 · count 구간마다, '모르겠어요'도 값 하나)
- 범주 안 격자: 거주 × 같이 하는 공정(없음 · 하나 · 여럿) × 면적 기준 × 조건 있는 칸, 나머지(면적 크기 · 발코니 ·
  준공 연도 · 공간 이름 수)는 값마다 고르게. dev:held-out 2:1, 공간 이름 조각은 나눔마다 따로
- 같은 입력 금지, 입력 글 꼴이 같고 면적 차이가 1평 안이면 근사 중복으로 거른다
- 기대: 계산 엔진 단계 키 · '실측 후' 줄, 꼭 언급(`sum.*` · `after.*` · `order.*` · `check.*` · `prep.mention`) ·
  언급하면 안 됨(`not_chosen.*` · `scope.*` · `empty.moving`). 규칙은 스펙 화면 말에서 뽑는다 (`scorers/trade_plan.py`)

| 공정 | 사례 | 범주 | 범주마다 (dev / held-out) |
| --- | ---: | --- | ---: |
| 도배 `dobae` | 4,995 | 도배 유형(저가형 · 기본형 · 모름) × 천장(함 · 안 함 · 모름) 9개 | 370 / 185 |
| 목공 `mokgong` | 4,995 | 목공 항목 조합 15개 (방문 개수 · 문틀은 격자) | 222 / 111 |

## 실행 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py                  # 등록된 공정 전부
uv run python ../evaluation/plan/make_cases.py --trade dobae    # 한 공정만
uv run python ../evaluation/check_cases.py --trade dobae        # 무료 점검 (T0)
```

다른 공정도 스펙이 등록돼 있으면 같은 한 줄이다 (설정 없이 스펙 화면 말로 규칙 · 모범 답을 만든다):

```bash
for t in floor tile bath kitchen electric window paint film; do
  uv run python ../evaluation/plan/make_cases.py --trade $t && uv run python ../evaluation/check_cases.py --trade $t
done
```

10공정이 등록된 통합 코드(aed4f67)에서 공정마다 600개로 돌려 T0 문제 0개를 확인했다. 실제로 돌리기 전에
그 공정 지식을 읽고 `config.py`에 규칙 손질이 필요한지 본다 (예: 도배의 발코니 결로 확인).

# 능동 에이전트 · 에이전트 평가 · LLM 판정 조사(2026-11-21)

조사 담당 하위 에이전트 보고를 정리했어요. 일부 수치는 논문 초록 기준이에요.
확인하지 못한 것: LightGBM 공식 문서(429 오류), IAAO 원문(카운티 요약 페이지로 대신함).

## 1. 능동 에이전트 설계
- 사람 확인은 세 종류예요.
  - 알림: 행동하지 않고 알리기
  - 질문: 막히면 묻기
  - 검토: 위험한 행동은 승인 뒤에 실행하고, 이 검토는 코드로 강제하기 [1]
- 끼어드는 때는 사용자의 쉬는 틈이에요. 에이전트가 있다는 표시와 참고 범위를 보여 주면 방해받는 느낌이 줄어요 [2]. 대화 중에는 '말할 동기 점수'로 끼어들지 정해요 [3].
- 먼저 제안하면 과업 완료가 12~18% 늘고 80~90%가 선호했어요. 그런데 '더 잦은 제안'은 절반만 좋아해서 빈도 상한이 필요해요 [4].
- 지표
  - 끼어들기 판단: 정밀도 · 재현율 · F1 · 거짓 경보율 [5]
  - 제안 수락률: 체감 생산성을 가장 잘 예측하는 지표(Copilot 연구) [6]
  - 원칙: 맥락에 맞는 시점, 쉬운 닫기 [7]
- 믿집에 옮기면
  - 트리거는 상태 전이로만 한정해요(견적서 도착 · 연기 요청 · N일 무응답).
  - 제안은 코드가 만들고 AI는 문장만 써요.
  - 화면 알림에는 하루 상한과 dedup을 둬요.
  - 확정 · 연락처 전달은 사람이 버튼으로 검토해요.

## 2. 에이전트 평가
- Anthropic 가이드 [8]
  - 경로보다 결과(최종 상태)를 먼저 채점해요.
  - 실제 실패 사례 20~50건으로 시작해요.
  - 능력 평가(낮은 통과율에서 출발)와 회귀 평가(≈100% 유지)를 나눠요.
  - 고객용은 pass^k로 봐요.
  - 대화형은 LLM 사용자 시뮬레이터 + 상태 확인 + 턴 제한 + 루브릭으로 봐요.
  - 대화 기록(트랜스크립트)을 직접 읽어요.
- τ-bench: 시뮬레이터와 대화한 뒤 DB 상태를 정답 상태와 비교하고 pass^k를 봐요 [9]. τ²-bench는 사용자도 도구를 쓰는 환경이에요 [10].
- 도구 호출 평가
  - 궤적 일치(완전 · 순서 · 순서 무관), 정밀도 · 재현율 [11]
  - 도구별 인자 일치 [12]
  - AST 검사와 '부르지 말아야 할 때' 판단 [13]

## 3. LLM 판정(LLM-as-a-judge)
- 형식
  - 명확한 루브릭과 구체적인 출력을 써요. 먼저 생각하게 한 뒤 점수를 받아요 [14].
  - 이진 pass/fail에 전문가 비평 few-shot을 붙여요 [15].
  - 버전 비교는 쌍대, 회귀 감시는 이진 루브릭으로 해요 [16].
- 위치 편향: 순서를 바꿔 두 번 판정하고, 둘 다 같은 쪽일 때만 승으로 쳐요(그 밖은 무승부). 기준 답을 주면 실패율이 70%에서 15%로 줄었어요 [17].
- 길이 편향: 길이 차이를 통제하자 아레나와의 상관이 0.94에서 0.98로 올랐어요 [18]. 판정문에 "길이로 점수 주지 말 것"을 넣어요.
- 자기 선호: 자기 글을 알아보는 능력과 선호 강도가 비례해요 [19]. 생성 모델과 다른 모델로 판정하고 라벨을 숨겨요.
- 사람과의 일치
  - 코헨 카파를 써요 [20].
  - 불량이 드물면 TPR · TNR로 봐요. 라벨은 train/dev/test로 나눠요 [15].
  - 차원별로 따로 판정하고 Unknown을 허용해요 [8].
- 비용: 강한 판정 모델로 맞춘 뒤 작은 모델로 바꿔 정확도 하락을 재요 [15]. Batch는 50% 할인이에요 [21].

## 4. 견적 정확도 지표(r = 표준견적 ÷ 실측 견적)
- 치우침: 중앙 비율, 로그 비율 평균. MAPE는 낮게 예측한 쪽에 유리해서 log 비율을 권장해요 [22].
- 오차 크기: MdAPE를 주로 쓰고 MAPE는 보조예요.
- 적중률: ±10% · ±20% 안에 든 비율(Zillow 방식) [23]
- 균일성: COD(≤15), PRD(0.98~1.03). 감정 비율 연구의 기준이에요 [24].
- 나눠 보기: 공정 · 평형 · 등급별로 봐요. 건수가 적으면 부트스트랩 95% 구간을 같이 적어요.

## 5. 작은 ML/DL 후보
| 후보 | 지표 | 메모 |
| --- | --- | --- |
| 입구 의도 분류 미세조정(SetFit · 한국어 인코더) [25][26] | macro-F1, 범위 밖 재현율, ECE, Jev로 넘기는 비율 | 라벨이 있으면 작은 미세조정 모델이 zero-shot LLM보다 나아요 |
| 검색 재순위(bge-reranker-v2-m3) [27][28] | Recall@k, nDCG@10, MRR | Anthropic 맥락 검색: 재순위 더해 검색 실패 67% 감소 |
| 업체 추천 랭킹 학습(LambdaRank) | nDCG@3, HitRate@3 | 가중치만 데이터로 두고 점수 계산은 calc에 둬요 |
| 실측 견적 구간 예측(분위수 회귀) | 구간 포함률, ±10% 적중률 | 금액을 만들면 calc 규칙과 부딪혀요. 이상치 표시 · 내부 평가에만 써요 |
| 능동 제안 수락 예측 | AUC, 수락률 변화 | 로그가 쌓인 뒤 |

## 6. 평가 계획 초안(목표는 예시, 첫 기준선을 잰 뒤 조정)
| 지표 | 측정 방법 | 목표 예시 |
| --- | --- | --- |
| 상담 완료율 pass^1 / pass^3 | 시나리오 × 3회, 끝 상태를 정답 상태와 비교 | ≥85% / ≥70% |
| 도구 호출 재현율 · 금지 호출 | 궤적 + 인자 비교 | ≥95% · 0건 |
| 회귀 세트 통과율 | 졸업 시나리오 + 새 실패 사례 | ≥98% |
| 숫자 일치 | 답의 금액 · 날짜를 calc 결과와 대조 | 불일치 노출 0건 |
| 능동 제안 수락률 | 표시 → 수락 로그 | ≥30% |
| 닫기 · 알림 끄기 비율 | 화면 로그 | ≤50% · ≤5% |
| 거짓 경보율 | 트리거 표본에 라벨 | ≤20% |
| 판정 모델 신뢰도 | 사람 라벨 100건과 카파, TPR · TNR | κ≥0.7, TNR≥0.9 |
| 판정 위치 일관성 | 순서를 바꿔도 같은 판정인 비율 | ≥90% |
| 표준견적 치우침 | 중앙 비율 | 0.95~1.05 |
| 표준견적 정확도 | MdAPE, ±20% 적중률 | ≤12%, ≥75% |
| 가견적 정확도 | 확정 실측 대비 MdAPE, ±10% 적중률 | ≤10%, ≥60% |
| 견적 균일성 | COD, PRD | ≤15, 0.98~1.03 |
| 의도 분류 | held-out macro-F1, ECE, 범위 밖 재현율 | ≥0.90, ≤0.05, ≥0.95 |
| 검색 재순위 | Recall@5, nDCG@10 | +10%p |
| 업체 추천 | nDCG@3 · HitRate@3 | 규칙 점수보다 높음 |
| 비용 · 지연 | 턴당 토큰, p90 지연 | 기준선 대비 +20% 이내 |

## 출처
1. https://blog.langchain.com/introducing-ambient-agents
2. https://arxiv.org/abs/2502.18658
3. https://arxiv.org/abs/2501.00383
4. https://arxiv.org/abs/2410.04596
5. https://arxiv.org/abs/2410.12361
6. https://cacm.acm.org/research/measuring-github-copilots-impact-on-productivity
7. https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/
8. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
9. https://arxiv.org/abs/2406.12045
10. https://arxiv.org/abs/2506.07982
11. https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-agents
12. https://github.com/langchain-ai/agentevals
13. https://proceedings.mlr.press/v267/patil25a.html
14. https://platform.claude.com/docs/en/test-and-evaluate/develop-tests
15. https://hamel.dev/blog/posts/evals-faq/ · https://hamel.dev/blog/posts/llm-judge/
16. https://eugeneyan.com/writing/llm-evaluators/
17. https://arxiv.org/abs/2306.05685
18. https://arxiv.org/abs/2404.04475
19. https://arxiv.org/abs/2404.13076
20. https://arxiv.org/abs/2406.12624
21. https://platform.claude.com/docs/en/about-claude/pricing
22. https://arxiv.org/abs/2105.05249
23. https://www.zillow.com/zestimate
24. https://santafecountynm.gov/assessor/resources/statistical-data
25. https://arxiv.org/abs/2209.11055
26. https://arxiv.org/abs/2406.08660
27. https://huggingface.co/BAAI/bge-reranker-v2-m3
28. https://www.anthropic.com/news/contextual-retrieval

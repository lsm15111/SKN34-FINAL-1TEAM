from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    """환경변수에서 읽는 설정. 값은 compose가 .env로 넣어 준다."""

    model_config = SettingsConfigDict(extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql+asyncpg://mitjip:mitjip@localhost:5432/mitjip"
    redis_url: str = "redis://localhost:6379/0"
    # 운영에서 /api 아래로 내보낼 때 문서 주소가 맞도록 쓰는 접두어
    api_root_path: str = ""
    # false면 LLM을 부르지 않고 스텁 응답을 쓴다 (유료 호출 0회)
    llm_live: bool = False
    # LLM 공급자: anthropic(기본, Claude) · openai. openai면 v4 비서 · 조사 · 기억 · 먼저 말 걸기도 OpenAI로 간다
    # (agent/llm.py OpenAI Responses 길, 도면 읽기만 Claude라 꺼짐). 임베딩은 공급자와 상관없이 OpenAI를 쓴다
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    # Claude 키. agent/llm.py만 읽는다. 키는 repr·오류에 표시하지 않는다
    anthropic_api_key: SecretStr = SecretStr("")
    # Claude API 주소. SDK가 환경의 ANTHROPIC_BASE_URL(다른 도구가 넣는 값)을 따라가지 않게 늘 이 값을 넘긴다
    llm_anthropic_base_url: str = "https://api.anthropic.com"
    # Claude 모델(agent/llm.py만 읽는다): 비서 · 도면 · 무거운 역할 / 짧은 문장 · 분류 · 기억 · 가벼운 역할 / 판정.
    # 이름 앞을 LLM_으로 둔다: CLAUDE_* · ANTHROPIC_* 환경변수는 Claude Code 같은 도구가 이미 쓴다
    llm_claude_model: str = "claude-sonnet-5-5"
    llm_claude_effort: Effort = "medium"
    llm_claude_light_model: str = "claude-haiku-5-5"
    llm_claude_light_effort: Effort = "low"
    llm_claude_judge_model: str = "claude-opus-5-5"  # 평가(evaluation)에서만
    # 가벼운 모델을 쓸 v2 · v3 역할(쉼표로)
    llm_claude_light_roles: str = "trade,composer,general,planner"
    # 유료 LLM 비용 상한(달러, usage.service). 80%면 경고 로그, 90%면 유료 호출을 막고 무료 모드로 답한다
    llm_cap_user_day_usd: float = 1.0
    llm_cap_service_day_usd: float = 5.0
    llm_cap_total_usd: float = 45.0
    # 새 계정(가입한 지 llm_new_user_days일 안) 몫: 한 계정 하루 · 새 계정 모두 합쳐 하루. 사용자 하루 상한과 함께 본다.
    # 일수를 0으로 두면 새 계정 몫을 보지 않는다
    llm_cap_new_user_day_usd: float = 0.20
    llm_cap_new_pool_day_usd: float = 1.0
    llm_new_user_days: int = 7
    # 비서 한 턴 상한(달러). 비서 runtime이 CALL_CTX.spent_micros와 비교한다
    llm_cap_turn_usd: float = 0.06
    # 비서 answer_question이 질문 종류별로 부를 답 파이프라인: v3(chat.service.answer_only) · v2(v2.ask.answer_only)
    # · v2g(v2.ask.grounds: v2 근거만, LLM 없이) · v2+v3 · v2g+v3(v2 먼저, v2 관문이 범위 밖으로 보고 v3가 답하면 v3).
    # 'v3'처럼 하나면 모두, 'price=v3,*=v2+v3'처럼
    # 종류=엔진을 쉼표로 적으면 그 종류만(* = 나머지, 없으면 v3). 기본값: 공정 에이전트는 전문지식만 넘기고 비서가 받아
    # 한 번에 정리한다(v2g, 2026-11-23 사용자 결정 · 판정 j-route-terra: 품질 비슷 · 턴 비용 41% 적고 35% 빠름).
    # expert · expert+v3: 코드가 공정(도배 · 목공 · 둘 다)을 고르고 공정 전문가(assistant/experts, LLM 구조화 답)가
    # 근거 번호 · 주의점 · 확인할 조건을 내면 비서가 받아 써요. 모르는 공정 · 실패는 v2g로 물러서요(docs/v4/13)
    # 기본(2026-11-24 리드, 사용자 '오케스트레이터 - 목공 · 도배' · Opus 판정 짝 비교 143문항): expert+v3.
    # 비교 67 +0.04 · 도배 · 목공 36 +0.56 [+0.14, +1.06] · K held-out 40 −0.20 [−0.60, +0.17] · 합 +0.10(같거나 나음)
    assistant_answer_route: str = "period=v3,price=v3,*=expert+v3"
    # 공정 전문가 모델: main = 비서와 같은 모델 · 강도(기본), light = 'trade' 목적 기본(가벼운 모델)
    assistant_expert_model: Literal["main", "light"] = "main"
    # 비서 지시문 판 묶음(assistant/prompts SETS): v5(기본, customer_v5 · vendor_v4 · nudge_write_v3) · v4 · v3(옛 판).
    # v5는 고객 지시문만 원칙으로 합쳐 줄인 판이다(11-25 A/B: 시나리오 25 × 2 · Opus 판정에서 v4와 같거나 나음).
    # 판마다 지시문 글이 달라 프롬프트 캐시도 판마다 따로 맞는다
    assistant_prompt_set: Literal["v3", "v4", "v5"] = "v5"
    # 비서 조사 담당(assistant/research.py): 공사당 하루(서울 날짜) 조사 시작 수. 0이면 세지 않는다
    assistant_research_day_max: int = 3
    # 수동 임베딩 CLI와 에이전트 LLM(agent/llm.py)이 쓴다. 키는 repr·오류에 표시하지 않는다.
    openai_api_key: SecretStr = SecretStr("")
    openai_embedding_model: str = "text-embedding-3-small"
    # true면 v3 AI 무료 모드도 질문 임베딩(의미 검색)으로 카드 · 조각을 다시 확인한다. 키가 없으면 키워드만
    ai_embed_free: bool = True
    # 상태를 바꾸는 요청(POST 등)에서 허용할 브라우저 Origin, 쉼표로 구분
    allowed_origins: str = "http://localhost:3000,http://localhost:3100"
    # 로그인 세션 유지 기간(일)
    session_days: int = 14
    # 몰릴 때(API 프로세스 하나마다). DB 풀(5 + 넘침 5)에서 빈 연결을 기다리는 초. 넘으면 503(Retry-After)
    db_pool_timeout: float = 3.0
    # 동시에 도는 대화 턴(비서 · 업체 비서 · AI 칸 SSE) 자리. 다 차면 기다리지 않고 503(Retry-After).
    # 기본 10 = 풀 연결 수(부하 재기 2026-11-22: 20이면 60명에서 풀 기다림 초과가 남고 10이면 30명까지 0)
    turn_slots: int = 10
    # 넘쳐서(턴 자리 · DB 풀) 503으로 거절할 때 다시 해 보라고 알려 줄 초(Retry-After)
    busy_retry_after: int = 5
    # 올린 파일을 두는 폴더. 운영에서 객체 저장소로 바꾸면 files/storage.py만 고친다
    files_dir: str = "./data/files"
    # 스테이징/운영에서만 사용. 비어 있으면 기존 로컬 디스크 저장소 유지
    files_s3_bucket: str = ""
    # true면 worker가 시연 업체(app/demo.py) 일을 몇 초마다 대신 한다. 운영에서는 켜도 돌지 않는다
    demo_auto: bool = False
    # OpenAI 길(LLM_PROVIDER=openai, 되돌리기용) 에이전트 LLM. agent/llm.py만 읽는다
    openai_agent_model: str = "gpt-6.1-terra"
    openai_reasoning_effort: str = "low"
    # 짧은 구조화 출력(공정 에이전트 등)에 쓰는 작은 모델. 비우면 openai_agent_model을 쓴다
    openai_light_model: str = "gpt-6-luna"
    openai_light_effort: str = "none"
    openai_light_roles: str = "trade,composer,general,planner"  # 작은 모델을 쓸 역할(쉼표로). composer = 답 작성기, planner = 질문 분석
    # 입구 관문. 학습 모델 신뢰도가 이보다 낮으면 Jev에 한 번 묻는다 (#70에서 0.7로 정함)
    intent_confidence_threshold: float = 0.7
    # Jev는 입구 분류에만 쓴다. 키는 repr·오류에 표시하지 않는다
    openrouter_api_key: SecretStr = SecretStr("")
    jev_model: str = "typesafe/jev-1.14"
    # false면 Jev를 부르지 않고 학습 모델 라벨을 그대로 쓴다 (Jev 효과 비교 테스트용)
    jev_enabled: bool = True
    # v3 실시간 줄기 키 앞말. 비우면 mj:{app_env} (테스트 · 묶음끼리 섞이지 않게 바꿀 수 있다)
    realtime_prefix: str = ""

    @property
    def is_https(self) -> bool:
        return self.app_env in ("staging", "production")

    @property
    def session_cookie(self) -> str:
        # https에서는 __Host- 접두어로 다른 하위 도메인이 덮어쓰지 못하게 한다
        return "__Host-mj_sid" if self.is_https else "mj_sid"

    @property
    def origins(self) -> set[str]:
        return {o.strip() for o in self.allowed_origins.split(",") if o.strip()}


settings = Settings()

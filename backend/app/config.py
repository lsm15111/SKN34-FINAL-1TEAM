from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # 수동 임베딩 CLI와 에이전트 LLM(agent/llm.py)이 쓴다. 키는 repr·오류에 표시하지 않는다.
    openai_api_key: SecretStr = SecretStr("")
    openai_embedding_model: str = "text-embedding-3-small"
    # 상태를 바꾸는 요청(POST 등)에서 허용할 브라우저 Origin, 쉼표로 구분
    allowed_origins: str = "http://localhost:3000,http://localhost:3100"
    # 로그인 세션 유지 기간(일)
    session_days: int = 14
    # 올린 파일을 두는 폴더. 운영에서 객체 저장소로 바꾸면 files/storage.py만 고친다
    files_dir: str = "./data/files"
    # 스테이징/운영에서만 사용. 비어 있으면 기존 로컬 디스크 저장소 유지
    files_s3_bucket: str = ""
    # true면 worker가 시연 업체(app/demo.py) 일을 몇 초마다 대신 한다. 운영에서는 켜도 돌지 않는다
    demo_auto: bool = False
    # 에이전트 LLM. agent/llm.py만 읽는다
    openai_agent_model: str = "gpt-6.1-terra"
    openai_reasoning_effort: str = "low"
    # 짧은 구조화 출력(공정 에이전트 등)에 쓰는 작은 모델. 비우면 openai_agent_model을 쓴다
    openai_light_model: str = "gpt-6-luna"
    openai_light_effort: str = "none"
    openai_light_roles: str = "trade"  # 작은 모델을 쓸 역할 (쉼표로)
    # 입구 관문. 학습 모델 신뢰도가 이보다 낮으면 Jev에 한 번 묻는다 (#70에서 0.7로 정함)
    intent_confidence_threshold: float = 0.7
    # Jev는 입구 분류에만 쓴다. 키는 repr·오류에 표시하지 않는다
    openrouter_api_key: SecretStr = SecretStr("")
    jev_model: str = "typesafe/jev-1.14"

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

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
    # Claude API 키. 비어 있으면 SDK가 다른 인증(환경변수 · 로그인 프로필)을 찾는다
    anthropic_api_key: str = ""
    # 에이전트가 쓰는 모델과 생각 깊이. 한 번 호출을 기다리는 최대 시간(초)
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    llm_timeout_s: float = 60.0
    # 역할별 모델 · 생각 깊이. 모델이 비어 있으면 llm_model을 쓴다
    # router: 상담 라우터 · expert: 공정 전문가 답 · plan: 공정 의견 · sourcing: 가견적 · judge: 평가 판정
    llm_model_router: str = ""
    llm_model_expert: str = ""
    llm_model_plan: str = ""
    llm_model_sourcing: str = ""
    llm_model_judge: str = ""
    llm_effort_router: str = "low"
    llm_effort_expert: str = "low"
    llm_effort_plan: str = "medium"
    llm_effort_sourcing: str = "low"
    llm_effort_judge: str = "low"
    # 공정 의견 캐시 시간(초). 입력이 같으면 LLM을 다시 부르지 않는다. 0이면 끈다
    llm_plan_cache_s: int = 86400
    # 상태를 바꾸는 요청(POST 등)에서 허용할 브라우저 Origin, 쉼표로 구분
    allowed_origins: str = "http://localhost:3000,http://localhost:3100"
    # 로그인 세션 유지 기간(일)
    session_days: int = 14
    # 올린 파일을 두는 폴더. 운영에서 객체 저장소로 바꾸면 files/storage.py만 고친다
    files_dir: str = "./data/files"

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

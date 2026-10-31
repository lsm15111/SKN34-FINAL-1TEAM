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
    # router: 상담 라우터 · expert: 공정 전문가 답 · plan: 공정 의견 · sourcing: 가견적
    llm_model_router: str = ""
    llm_model_expert: str = ""
    llm_model_plan: str = ""
    llm_model_sourcing: str = ""
    llm_effort_router: str = "low"
    llm_effort_expert: str = "low"
    llm_effort_plan: str = "medium"
    llm_effort_sourcing: str = "low"
    # 공정 의견 캐시 시간(초). 입력이 같으면 LLM을 다시 부르지 않는다. 0이면 끈다
    llm_plan_cache_s: int = 86400
    # 상태를 바꾸는 요청(POST 등)에서 허용할 브라우저 Origin, 쉼표로 구분
    allowed_origins: str = "http://localhost:3000,http://localhost:3100"
    # 로그인 세션 유지 기간(일)
    session_days: int = 14
    # 올린 파일을 두는 폴더. 운영에서 객체 저장소로 바꾸면 files/storage.py만 고친다
    files_dir: str = "./data/files"
    # ── 외부 업체 정보 (가견적) ──
    # 공공데이터포털 서비스 키(KISCON 건설업체 · 국세청 사업자 상태). 비어 있으면 수집 작업을 건너뛴다
    data_go_kr_key: str = ""
    # 카카오 REST API 키 (선택). 있으면 외부 업체의 카카오맵 장소 ID만 맞춘다. 비어 있으면 건너뛴다
    kakao_rest_key: str = ""
    # 수집기 User-Agent에 붙일 연락 주소 (사이트 운영자가 믿집에 연락할 곳)
    bot_contact_url: str = ""
    # 홈페이지 확인기: 요청 사이 간격(초)과 한 요청을 기다리는 시간(초)
    crawl_interval_s: float = 3.0
    crawl_timeout_s: float = 10.0
    # 외부 업체에 믿집이 대신 연락하기. 법무 검토 전에는 끈다 (끄면 요청은 queued에서 멈춘다)
    contact_send_enabled: bool = False
    # 대신 연락 하루 한도 (서울 날짜): 고객 한 명이 만드는 요청 수, 업체 한 곳이 받는 요청 수
    contact_daily_per_customer: int = 5
    contact_daily_per_vendor: int = 2
    # 대신 연락 메시지 끝에 밝힐 발신자(믿집) 연락처. 비어 있으면 켜져 있어도 보내지 않는다
    contact_sender_contact: str = ""
    # 수신거부 링크를 만들 웹 주소
    web_url: str = "http://localhost:3000"

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

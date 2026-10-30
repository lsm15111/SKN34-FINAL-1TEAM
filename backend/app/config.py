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
    # 상태를 바꾸는 요청(POST 등)에서 허용할 브라우저 Origin, 쉼표로 구분
    allowed_origins: str = "http://localhost:3000,http://localhost:3100"

    @property
    def origins(self) -> set[str]:
        return {o.strip() for o in self.allowed_origins.split(",") if o.strip()}


settings = Settings()

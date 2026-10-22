from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TWINGATE_", env_file=".env", extra="ignore")

    network: str
    api_key: SecretStr
    page_size: int = Field(default=100, ge=1, le=100)
    default_limit: int = Field(default=100, ge=1)
    max_limit: int = Field(default=1000, ge=1)
    timeout_seconds: float = Field(default=30, gt=0)
    retry_attempts: int = Field(default=5, ge=1)
    mcp_http_token: SecretStr | None = Field(default=None, min_length=1)
    log_level: str = "INFO"

    @property
    def endpoint(self) -> str:
        return f"https://{self.network}.twingate.com/api/graphql/"


def describe_errors(exc: ValidationError) -> str:
    """Name the offending variables without echoing their values."""
    lines = [
        f"TWINGATE_{'_'.join(str(p) for p in err['loc']).upper()}: {err['msg']}"
        for err in exc.errors()
    ]
    return "Invalid settings:\n  " + "\n  ".join(lines)

from typing import Annotated, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TWINGATE_", env_file=".env", extra="ignore")

    network: str = Field(pattern=r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$")
    api_key: SecretStr
    page_size: int = Field(default=100, ge=1, le=100)
    default_limit: int = Field(default=100, ge=1)
    max_limit: int = Field(default=1000, ge=1)
    timeout_seconds: float = Field(default=30, gt=0)
    retry_attempts: int = Field(default=5, ge=1)
    mcp_http_token: SecretStr | None = Field(default=None, min_length=1)
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = []
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("mcp_allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [h.strip() for h in value.split(",") if h.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

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

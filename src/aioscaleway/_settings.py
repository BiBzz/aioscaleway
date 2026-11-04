from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScalewaySettings(BaseSettings):
    """Connection settings, read from the `SCW_*` variables of the official CLI."""

    model_config = SettingsConfigDict(env_prefix="SCW_", extra="ignore")

    secret_key: SecretStr | None = None
    access_key: str | None = None
    api_url: str = "https://api.scaleway.com"
    default_region: str | None = None
    default_zone: str | None = None
    default_organization_id: str | None = None
    default_project_id: str | None = None
    timeout: float = 60.0
    retry_attempts: int = 5
    retry_timeout: float | None = 120.0
    retry_wait_initial: float = 0.5
    retry_wait_max: float = 30.0
    user_agent: str = "aioscaleway"

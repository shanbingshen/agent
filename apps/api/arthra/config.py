from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_secret_key: str = "development-only-change-me"
    access_token_expire_minutes: int = 30
    database_url: str = "postgresql+psycopg://arthra:arthra@localhost:5432/arthra"
    langgraph_database_url: str = ""
    langgraph_checkpoint_namespace: str = "arthra-agent-v2"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    bootstrap_admin_email: str = "admin@arthra.local"
    bootstrap_admin_password: str = "Arthra@123456"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.1
    supervisor_semantic_routing_enabled: bool = True
    supervisor_llm_model: str = ""
    supervisor_route_confidence_threshold: float = Field(default=0.65, ge=0, le=1)
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 384

    thingsboard_url: str = "http://localhost:9090"
    thingsboard_username: str = "tenant@thingsboard.org"
    thingsboard_password: str = "tenant"
    thingsboard_request_timeout: float = 15

    daily_summary_enabled: bool = True
    daily_summary_hour: int = Field(default=8, ge=0, le=23)
    daily_summary_timezone: str = "Asia/Shanghai"

    compressor_default_system_id: str = "AIR-SYS-01"
    compressor_analysis_window_hours: int = Field(default=24, ge=1, le=744)
    compressor_history_interval_seconds: int = Field(default=180, ge=30, le=3600)
    compressor_min_data_coverage: float = Field(default=0.8, ge=0, le=1)
    compressor_min_pressure_mpa: float = Field(default=0.65, ge=0)
    compressor_max_pressure_mpa: float = Field(default=0.8, ge=0)
    compressor_pressure_fluctuation_warning_mpa: float = Field(default=0.08, ge=0)
    compressor_idle_warning_minutes: float = Field(default=30, ge=0)
    compressor_unload_rate_warning_pct: float = Field(default=20, ge=0, le=100)
    compressor_frequent_starts_per_hour: float = Field(default=6, ge=0)
    compressor_production_start_hour: int = Field(default=8, ge=0, le=23)
    compressor_production_end_hour: int = Field(default=18, ge=0, le=23)
    compressor_unload_savings_factor: float = Field(default=0.5, ge=0, le=1)

    control_plan_ttl_seconds: int = 600
    control_allowed_methods: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["setPowerLimit", "setMode", "start", "stop"]
    )
    control_allowed_device_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["ems", "meter", "compressor"]
    )
    control_max_power_limit_kw: float = 500

    @field_validator("cors_origins", "control_allowed_methods", "control_allowed_device_types", mode="before")
    @classmethod
    def split_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

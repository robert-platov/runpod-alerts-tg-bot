from datetime import time
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    runpod_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    daily_notify_time: str = "12:00"
    daily_notify_tz: str = "UTC"
    low_balance_usd: float = 4000.0
    alert_initial_interval_minutes: float = 120.0
    alert_decay_factor: float = 0.5
    alert_minimum_interval_minutes: float = 15.0
    alert_hysteresis_usd: float = 2.0
    poll_interval_sec: float = 300.0
    log_level: str = Field(default="INFO")

    @field_validator("log_level")
    @classmethod
    def uppercase_log_level(cls, v: str) -> str:
        return v.upper()

    def get_daily_notify_time(self) -> time:
        parts = self.daily_notify_time.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return time(hour=hour, minute=minute)

    def get_daily_notify_tz(self) -> ZoneInfo:
        return ZoneInfo(self.daily_notify_tz)


def load_config() -> AppConfig:
    return AppConfig()

"""Configuration loading utilities for the alert bot."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

# Load environment variables from .env file (if it exists)
load_dotenv()


@dataclass(frozen=True)
class Config:
    """Application configuration loaded from environment variables."""

    sensor_tower_api_key: str
    slack_webhook_url: str


def _get_required_env_var(name: str) -> str:
    """Return a required environment variable or raise a clear error."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Please set it before running integrations."
        )
    return value


def load_config() -> Config:
    """Load application configuration from environment variables."""
    return Config(
        sensor_tower_api_key=_get_required_env_var("SENSOR_TOWER_API_KEY"),
        slack_webhook_url=_get_required_env_var("SLACK_WEBHOOK_URL"),
    )
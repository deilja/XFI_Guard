"""Pydantic models for AI provider and consensus settings."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Provider = Literal["gemini", "groq", "openrouter", "routerai"]


class AISettings(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    provider: Provider = "gemini"
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "openai/gpt-oss-20b"
    openrouter_model: str = "openrouter/free"
    openrouter_models: tuple[str, ...] = ()
    routerai_model: str = ""
    routerai_models: tuple[str, ...] = ()
    routerai_enabled: bool = False
    # Paid RouterAI inference is opt-in. Free models remain the default.
    routerai_allow_paid: bool = False
    gemini_key: str = ""
    groq_key: str = ""
    openrouter_key: str = ""
    routerai_key: str = ""
    ai_weights: dict[Provider, float] = Field(default_factory=lambda: {"gemini": 1.0, "groq": 1.0, "openrouter": 1.0, "routerai": 1.0})
    ai_min_consensus: float = Field(default=0.60, ge=0.0, le=1.0)
    ai_timeout: float = Field(default=20.0, gt=0.0, le=300.0)
    ai_max_workers: int = Field(default=6, ge=1, le=8)
    ai_cooldown: float = Field(default=30.0, ge=0.0, le=300.0)

    @field_validator("openrouter_models", "routerai_models")
    @classmethod
    def normalize_model_list(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        result: list[str] = []
        for item in value:
            model = str(item).strip()
            if model and model not in seen:
                seen.add(model)
                result.append(model)
        return tuple(result)

    @field_validator("ai_weights")
    @classmethod
    def validate_weights(cls, value: dict[Provider, float]) -> dict[Provider, float]:
        result = {"gemini": 1.0, "groq": 1.0, "openrouter": 1.0, "routerai": 1.0}
        for provider, weight in value.items():
            if weight <= 0:
                raise ValueError(f"AI weight for {provider} must be > 0")
            result[provider] = float(weight)
        return result


class DefenseSettings(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    enabled: bool = False
    confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    min_attempts: int = Field(default=5, ge=1, le=10000)
    db: str = "/var/lib/xfi-guard/security.db"


class MonitorSettings(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    output_file: str = "/var/log/xfi-guard/monitor.jsonl"
    state_file: str = "/var/lib/xfi-guard/state.json"
    disk_warning_percent: int = Field(default=85, ge=1, le=100)
    memory_warning_percent: int = Field(default=90, ge=1, le=100)
    vpn_services: tuple[str, ...] = ("xray", "x-ui", "3x-ui")
    vpn_ports: tuple[int, ...] = (22, 80, 443, 2053, 2083, 2087, 2096)
    ssh_log: str = "/var/log/auth.log"
    fail2ban_log: str = "/var/log/fail2ban.log"
    max_events_per_cycle: int = Field(default=100, ge=1, le=10000)
    telegram_enabled: bool = False
    telegram_cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    ai_provider: Provider = "gemini"
    ai_max_events_per_cycle: int = Field(default=10, ge=0, le=10000)
    auto_block_enabled: bool = False
    auto_block_confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    auto_block_min_attempts: int = Field(default=5, ge=1, le=10000)
    auto_block_db: str = "/var/lib/xfi-guard/security.db"

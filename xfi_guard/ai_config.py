"""Validated AI configuration schema."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Provider = Literal["gemini", "groq", "openrouter"]


class AIWeights(BaseModel):
    model_config = ConfigDict(extra="ignore")
    gemini: float = Field(default=1.0, ge=0.0)
    groq: float = Field(default=1.0, ge=0.0)
    openrouter: float = Field(default=1.0, ge=0.0)


class AIConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Provider = "gemini"
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "openai/gpt-oss-20b"
    openrouter_model: str = "openai/gpt-oss-20b"
    openrouter_models: list[str] = Field(default_factory=list)
    gemini_key: str = ""
    groq_key: str = ""
    openrouter_key: str = ""
    ai_weights: AIWeights = Field(default_factory=AIWeights)
    ai_min_consensus: float = Field(default=0.60, ge=0.0, le=1.0)
    ai_timeout: float = Field(default=20.0, gt=0.0, le=300.0)
    ai_max_workers: int = Field(default=6, ge=1, le=8)
    ai_cooldown: float = Field(default=30.0, ge=0.0, le=3600.0)

    @field_validator("gemini_model", "groq_model", "openrouter_model")
    @classmethod
    def model_name_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model name cannot be empty")
        return value

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")

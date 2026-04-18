"""Analysis configuration models and loader.

The YAML wiring (pyyaml is declared but not yet imported anywhere) is
deferred to Phase 1.5 together with the APScheduler and LiteLLM wiring.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from .types import Sensitivity


class BriefingConfig(BaseModel):
    enabled: bool = True
    cron: str = "0 7 * * *"
    lookback_days: int = 1
    baseline_days: int = 30


class WeeklyConfig(BaseModel):
    enabled: bool = True
    cron: str = "0 8 * * 1"
    lookback_days: int = 7
    baseline_days: int = 28


class AnomalyConfig(BaseModel):
    enabled: bool = True
    cron: str = "*/30 * * * *"
    on_ingest: bool = True
    cooldown_minutes: int = 15
    sensitivity: Sensitivity = "normal"


class TrendConfig(BaseModel):
    enabled: bool = True
    cron: str = "0 9 * * 1"
    period_days: int = 30


class CorrelationConfig(BaseModel):
    enabled: bool = True
    cron: str = "0 10 1 * *"
    period_days: int = 90


class LLMFallbackEntry(BaseModel):
    provider: str
    model: str


class LLMConfig(BaseModel):
    provider: str = "ollama"
    model: str = "llama3.1:8b"
    base_url: str = "http://ollama:11434"
    api_key: str = ""
    temperature: float = 0.3
    max_tokens: int = 1000
    fallback: list[LLMFallbackEntry] = Field(default_factory=list)


class MQTTConfig(BaseModel):
    enabled: bool = False
    broker: str = "localhost"
    port: int = 1883
    topic_prefix: str = "health/insights"


class NotificationsConfig(BaseModel):
    webhook_url: str = ""
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)


class AnalysisConfig(BaseModel):
    """Top-level analysis config, loaded from ``config.yaml``."""

    daily_briefing: BriefingConfig = Field(default_factory=BriefingConfig)
    weekly_summary: WeeklyConfig = Field(default_factory=WeeklyConfig)
    anomaly_detection: AnomalyConfig = Field(default_factory=AnomalyConfig)
    trend_analysis: TrendConfig = Field(default_factory=TrendConfig)
    correlation_analysis: CorrelationConfig = Field(default_factory=CorrelationConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)


def load_config(path: Path) -> AnalysisConfig:
    """Load ``config.yaml`` into :class:`AnalysisConfig`.

    Will parse YAML via ``pyyaml`` (already declared as a dependency)
    and validate against the Pydantic models above.
    """
    raise NotImplementedError(
        "YAML loading deferred to Phase 1.5 — pyyaml dep installed, not yet wired"
    )

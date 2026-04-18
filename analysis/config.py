"""Analysis configuration models and loader.

Phase 1.5 activation: ``load_config`` now parses ``config.yaml`` via
``pyyaml`` (imported lazily to keep module import cheap) and validates
the structure against the Pydantic models below. The top-level YAML
shape is::

    analysis:
      daily_briefing: { enabled, cron, lookback_days, baseline_days }
      weekly_summary: { ... }
      anomaly_detection: { ... }
      trend_analysis: { ... }
      correlation_analysis: { ... }
    llm: { provider, model, base_url, ... }
    notifications: { webhook_url, mqtt: { ... } }

which maps to :class:`AnalysisConfig` (analysis / llm / notifications).
"""

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from .types import Sensitivity

log = logging.getLogger("healthsave.analysis")


class ConfigError(ValueError):
    """Raised when ``config.yaml`` is present but cannot be parsed or validated."""


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


class AnalysisBlock(BaseModel):
    """The ``analysis:`` sub-tree of ``config.yaml``."""

    daily_briefing: BriefingConfig = Field(default_factory=BriefingConfig)
    weekly_summary: WeeklyConfig = Field(default_factory=WeeklyConfig)
    anomaly_detection: AnomalyConfig = Field(default_factory=AnomalyConfig)
    trend_analysis: TrendConfig = Field(default_factory=TrendConfig)
    correlation_analysis: CorrelationConfig = Field(default_factory=CorrelationConfig)


class AnalysisConfig(BaseModel):
    """Top-level analysis config, loaded from ``config.yaml``."""

    analysis: AnalysisBlock = Field(default_factory=AnalysisBlock)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)


def load_config(path: Path | str) -> AnalysisConfig:
    """Load ``config.yaml`` into :class:`AnalysisConfig`.

    * Missing file → return defaults (local-first, zero-config startup).
    * Malformed YAML → raise :class:`ConfigError`.
    * Valid YAML → Pydantic ``model_validate`` (raises ValidationError on
      schema violations, which we let bubble up untouched).
    """
    path = Path(path)
    if not path.exists():
        log.info("config.yaml not found at %s; using defaults", path)
        return AnalysisConfig()

    import yaml  # deferred import, keeps module-load light

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"malformed config.yaml at {path}: {exc}") from exc
    return AnalysisConfig.model_validate(data)

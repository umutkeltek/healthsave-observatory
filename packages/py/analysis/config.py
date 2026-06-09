"""Analysis configuration models and loader.

Phase 2 activation: ``load_config`` parses ``config.yaml`` via
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
import os
from pathlib import Path

from pydantic import BaseModel, Field

from .types import Sensitivity

log = logging.getLogger("healthsave.analysis")


class ConfigError(ValueError):
    """Raised when ``config.yaml`` is present but cannot be parsed or validated."""


class BriefingConfig(BaseModel):
    enabled: bool = False
    cron: str = "0 7 * * *"
    lookback_days: int = 1
    baseline_days: int = 30


class WeeklyConfig(BaseModel):
    enabled: bool = False
    cron: str = "0 8 * * 1"
    lookback_days: int = 7
    baseline_days: int = 28


class AnomalyConfig(BaseModel):
    enabled: bool = False
    cron: str = "*/30 * * * *"
    on_ingest: bool = True
    cooldown_minutes: int = 15
    sensitivity: Sensitivity = "normal"


class TrendConfig(BaseModel):
    enabled: bool = False
    cron: str = "0 9 * * 1"
    period_days: int = 30


class CorrelationConfig(BaseModel):
    enabled: bool = False
    cron: str = "0 10 1 * *"
    period_days: int = 90


class RecoveryConfig(BaseModel):
    enabled: bool = False
    cron: str = "0 6 * * *"  # 6:00 AM, ahead of the 7:00 AM daily briefing
    lookback_days: int = 1
    baseline_days: int = 30


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
    # Egress trust boundary (ADR-0001 Decision G). Default-deny: a cloud
    # provider also needs this explicit opt-in before any derived data leaves
    # the host. Local Ollama is unaffected. Raw observations never leave.
    allow_cloud_egress: bool = False
    # Content redaction (analysis/redaction.py). When a prompt is allowed out to
    # a CLOUD provider, scrub identifiers (emails, phones, IDs, names) from it
    # first. Default-on so the opt-in cloud tier is safe by construction; the
    # local Ollama path is never redacted. ``redaction_salt`` only affects the
    # optional hashed-token method (stable pseudonyms across prompts).
    redact_cloud_prompts: bool = True
    redaction_salt: str = ""


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
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)


class AnalysisConfig(BaseModel):
    """Top-level analysis config, loaded from ``config.yaml``."""

    analysis: AnalysisBlock = Field(default_factory=AnalysisBlock)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)


# .env name -> AnalysisBlock attribute for the per-job enable flag. The remote
# deploy mounts config.yaml.example (every job off) and wipes any host
# config.yaml on redeploy, so the persistent .env in REMOTE_ENV_DIR is the only
# deploy-survivable way to turn a Brain-1 job on in production.
_JOB_ENABLE_ENV: dict[str, str] = {
    "ANALYSIS_DAILY_BRIEFING_ENABLED": "daily_briefing",
    "ANALYSIS_WEEKLY_SUMMARY_ENABLED": "weekly_summary",
    "ANALYSIS_ANOMALY_DETECTION_ENABLED": "anomaly_detection",
    "ANALYSIS_TREND_ANALYSIS_ENABLED": "trend_analysis",
    "ANALYSIS_CORRELATION_ANALYSIS_ENABLED": "correlation_analysis",
    "ANALYSIS_RECOVERY_ENABLED": "recovery",
}


def _env_bool(name: str) -> bool | None:
    """Parse a boolean .env value, or None when the var is unset."""
    raw = os.getenv(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _with_environment_overrides(config: AnalysisConfig) -> AnalysisConfig:
    """Let Docker/.env values override checked-in YAML defaults."""
    llm_updates = {}
    if provider := os.getenv("LLM_PROVIDER"):
        llm_updates["provider"] = provider
    # LLM_MODEL is the explicit, provider-agnostic route (e.g.
    # "deepseek/deepseek-chat", "openrouter/google/gemini-2.0-flash-001") and
    # wins; OLLAMA_MODEL is the Ollama-specific alias kept for back-compat. A
    # cloud provider must set LLM_MODEL — OLLAMA_MODEL's compose default
    # ("llama3.1:8b") would otherwise silently pin every provider to that model.
    if model := os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL"):
        llm_updates["model"] = model
    if base_url := os.getenv("LLM_BASE_URL"):
        llm_updates["base_url"] = base_url
    if api_key := os.getenv("LLM_API_KEY"):
        llm_updates["api_key"] = api_key
    if (flag := _env_bool("LLM_ALLOW_CLOUD_EGRESS")) is not None:
        llm_updates["allow_cloud_egress"] = flag
    if (flag := _env_bool("LLM_REDACT_CLOUD_PROMPTS")) is not None:
        llm_updates["redact_cloud_prompts"] = flag
    if salt := os.getenv("LLM_REDACTION_SALT"):
        llm_updates["redaction_salt"] = salt
    # LLM_FALLBACK: comma-separated litellm model routes tried in order after the
    # primary, e.g. "openrouter/google/gemini-2.0-flash-001,ollama/llama3.2:3b".
    # The provider is the route's first segment (drives the egress re-check); a
    # cloud fallback still needs the opt-in, a local (ollama) one is always
    # allowed. config.yaml is wiped on redeploy, so this is the durable home.
    if fallback_raw := os.getenv("LLM_FALLBACK"):
        entries: list[LLMFallbackEntry] = []
        for route in (r.strip() for r in fallback_raw.split(",")):
            if not route:
                continue
            provider = route.split("/", 1)[0]
            # Ollama models carry a bare tag (the client re-adds the "ollama/"
            # prefix); cloud routes keep their full litellm path.
            model = route.split("/", 1)[1] if provider == "ollama" and "/" in route else route
            entries.append(LLMFallbackEntry(provider=provider, model=model))
        if entries:
            llm_updates["fallback"] = entries

    if llm_updates:
        config.llm = config.llm.model_copy(update=llm_updates)

    # Per-job enable overrides (see _JOB_ENABLE_ENV).
    analysis_updates = {}
    for env_name, attr in _JOB_ENABLE_ENV.items():
        flag = _env_bool(env_name)
        if flag is not None:
            block = getattr(config.analysis, attr)
            analysis_updates[attr] = block.model_copy(update={"enabled": flag})
    if analysis_updates:
        config.analysis = config.analysis.model_copy(update=analysis_updates)

    return config


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
        return _with_environment_overrides(AnalysisConfig())

    import yaml  # deferred import, keeps module-load light

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"malformed config.yaml at {path}: {exc}") from exc
    return _with_environment_overrides(AnalysisConfig.model_validate(data))

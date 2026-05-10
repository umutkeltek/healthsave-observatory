"""Pydantic model for inbound metric batches from HealthSave clients."""

from typing import Any

from pydantic import BaseModel, Field


class BatchPayload(BaseModel):
    metric: str = "unknown"
    batch_index: int = Field(default=0)
    total_batches: int = Field(default=1)
    samples: list[dict[str, Any]] = Field(default_factory=list)

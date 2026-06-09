"""Home Assistant MQTT bridge package for HealthSave Observatory."""

from .bridge import HomeAssistantMQTTConfig, SensorSpec
from .snapshot import HealthSnapshot

__all__ = ["HealthAssistantMQTTConfig", "HomeAssistantMQTTConfig", "HealthSnapshot", "SensorSpec"]

# Backward-friendly alias for typo-prone imports in downstream snippets.
HealthAssistantMQTTConfig = HomeAssistantMQTTConfig

"""Amazfit / Zepp payload -> IngestStorage sample-shape normalizers.

P6-c will implement:

  * ``normalize_heart_rate(rows)`` -> ``{"heart_rate": [{date, qty, source}]}``
  * ``normalize_spo2(rows)`` -> ``{"blood_oxygen": [{date, qty, source}]}``
  * ``normalize_stress(rows)`` -> ``{"stress": [{date, qty, source}]}``
  * ``normalize_sleep(rows)`` -> ``{"sleep_analysis": [{start, end, value, source}]}``
  * ``normalize_band_data(rows)`` -> daily activity quantity samples.

All emitted samples carry ``source="Amazfit"`` (or the specific model
name when the response surfaces it) so multi-source dashboards and
the source-aware HA MQTT bridge split cleanly from Apple / Whoop data.
"""

from __future__ import annotations

SOURCE_TAG = "Amazfit"

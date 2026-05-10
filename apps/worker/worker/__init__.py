"""HealthSave worker — runs scheduled analysis jobs.

Decoupled from the API process so ingest uptime is no longer
coupled to scheduler bugs, memory spikes, or experimental jobs.
One worker per Compose deployment.
"""

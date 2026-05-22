"""Whoop developer API paginated fetch — P2 implementation.

P1 ships an empty shell so the plugin layout matches its eventual
shape. P2 will fill in:

  * ``fetch_recovery(http_client, token, *, since)`` → normalized recovery rows
    (one per cycle; carries resting HR, HRV (RMSSD), SpO2, skin temp,
    recovery score).
  * ``fetch_sleep(http_client, token, *, since)`` → normalized sleep
    session rows + per-stage breakdown so ``sleep_sessions`` and
    ``sleep_stages`` populate the same way as Apple-sourced sleep.
  * ``fetch_workouts(http_client, token, *, since)`` → workout rows
    matching the iOS shape: duration, average + max HR, calories,
    HR-zone durations, strain.
  * ``fetch_cycles(http_client, token, *, since)`` → daily strain +
    HR summary; emitted as ``daily_activity`` derived rows.

Each normalizer must:

  * Carry a ``source`` of ``"whoop"`` so multi-source dashboards and
    the source-aware MQTT bridge can split it out.
  * Use the same field names the Apple plugin uses on each table so
    the dedup unique indexes apply without per-source branches.
  * Skip rows that fail the ``date`` + ``qty`` validation rather than
    fail the whole batch (existing behaviour for the Apple plugin).
"""

from __future__ import annotations

"""Zepp / Amazfit data-API paginated fetch — P6-b implementation.

P6-a ships an empty shell so the plugin layout matches its eventual
final form. P6-b will fill in:

  * ``fetch_band_data(http, token, *, day)`` -> aggregated daily JSON
    (steps, sleep, heart rate). ``day`` is a date string in
    ``YYYY-MM-DD``; the endpoint returns base64-encoded binary blobs
    plus a side-channel summary JSON.
  * ``fetch_heart_rate(http, token, *, since)`` -> per-minute HR rows.
  * ``fetch_spo2(http, token, *, since)`` -> oxygen saturation
    readings (newer models only).
  * ``fetch_stress(http, token, *, since)`` -> stress score readings.
  * ``fetch_sleep(http, token, *, since)`` -> sleep stage breakdowns.

Each fetcher accepts an injected :class:`HttpClient`-shaped object
and the OAuthToken returned by :func:`plugins.sources.amazfit.auth.login`.
Bearer-style header: ``apptoken: <app_token>``, ``appname:
com.huami.midong``. Base URL comes from the token's ``metadata``
``base_url`` field so a US/EU/CN account is read against the right
region without re-loading config.

Wire-shape fragility note: Zepp's data endpoints change incrementally
every few months. Each fetcher gets its own test fixture so a wire
change surfaces as a single named failure rather than a vague
``KeyError`` from deep in the normalizer.
"""

from __future__ import annotations

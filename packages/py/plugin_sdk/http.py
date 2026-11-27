# SPDX-License-Identifier: Apache-2.0
"""Bounded retry for a source plugin's vendor GETs.

A vendor that fails one request in twenty (a 503 from a load balancer, a read
timeout) used to fail the whole poll: a 30-day backfill window is dozens of
requests, so it almost never completed and was eventually given up as a gap.
:func:`get_with_retry` retries ONE request a few times with exponential
backoff when the failure says nothing about the request itself: a 408, 429 or
5xx answer, or a timeout / connection error. Every other answer is returned
as is for the caller to judge, and the last attempt's answer or error is what
the caller sees, so a real outage still fails the poll.
"""

from __future__ import annotations

import asyncio
from typing import Any

RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY_S = 1.0
MAX_DELAY_S = 10.0


async def _sleep(seconds: float) -> None:
    # Indirection so tests can make the backoff instant.
    await asyncio.sleep(seconds)


def _is_transient_transport_error(exc: BaseException) -> bool:
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx ships with every source plugin
        return isinstance(exc, TimeoutError | ConnectionError)
    return isinstance(exc, httpx.TimeoutException | httpx.NetworkError | httpx.RemoteProtocolError)


def _retry_after(response: Any) -> float | None:
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None  # an HTTP date: fall back to the backoff


async def get_with_retry(
    http_client: Any,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_S,
) -> Any:
    """``http_client.get(url, ...)``, retried on a transient failure.

    Retries a 408/429/5xx answer or a timeout / network error up to
    ``attempts`` tries in all, waiting ``base_delay`` doubled each time (a
    ``Retry-After`` in seconds wins), never more than :data:`MAX_DELAY_S`.
    Returns the last response (the caller checks its status) or raises the
    last error.
    """
    kwargs: dict[str, Any] = {"headers": headers}
    if params is not None:
        kwargs["params"] = params
    for attempt in range(1, attempts + 1):
        try:
            response = await http_client.get(url, **kwargs)
        except Exception as exc:
            if attempt == attempts or not _is_transient_transport_error(exc):
                raise
            delay = base_delay * 2 ** (attempt - 1)
        else:
            if getattr(response, "status_code", None) not in RETRYABLE_STATUSES:
                return response
            if attempt == attempts:
                return response
            delay = _retry_after(response)
            if delay is None:
                delay = base_delay * 2 ** (attempt - 1)
        await _sleep(min(delay, MAX_DELAY_S))
    raise AssertionError("unreachable")  # pragma: no cover


__all__ = ["RETRYABLE_STATUSES", "get_with_retry"]

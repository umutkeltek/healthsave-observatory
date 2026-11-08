"""Source-plugin poll registration for the worker scheduler.

Each source adapter still exposes a small named wrapper, but the runtime poll
lifecycle is owned by :func:`make_source_poll`: locate manifest, instantiate
plugin, open HTTP/session resources, call ``ingest()``, commit or rollback.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from storage.timescale.fusion import default_repository as default_fusion_repository

from contracts import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, PluginManifest

log = logging.getLogger("healthsave.worker.sources")

WHOOP_DEFAULT_CRON = "*/30 * * * *"
AMAZFIT_DEFAULT_CRON = "*/30 * * * *"
POLAR_DEFAULT_CRON = "*/30 * * * *"
GOOGLE_HEALTH_DEFAULT_CRON = "*/30 * * * *"

# After an outage longer than a plugin's own lookback, the next poll reaches
# back to the last successful poll, but never further than this: one poll
# must not ask a vendor for unbounded history.
MAX_BACKFILL = timedelta(days=30)
# A widened window that failed this many polls in a row (a vendor page cap, a
# range the vendor rejects) is given up: the next poll uses the plugin's
# default window again and the gap is recorded on the cursor and logged.
MAX_BACKFILL_FAILURES = 3
# A plugin that skipped the poll because no token is stored sets this key in
# its result; nothing was polled, so the cursor must not move.
SKIPPED_NO_TOKEN = "skipped_no_token"


@dataclass(frozen=True, slots=True)
class SourcePollSpec:
    """Adapter-specific inputs for the shared source poll lifecycle."""

    slug: str
    entrypoint: str
    log_label: str
    # The plugin's data-fetch error ("module:Class"). Only these count as a
    # failed backfill window; None counts nothing.
    fetch_error: str | None = None
    # The provider id the plugin stores its OAuth token under. The poll cursor
    # is keyed by it, so authorizing a token can reset the cursor's backfill
    # attempts (storage.timescale.oauth_tokens.put_token). Defaults to slug.
    token_provider: str | None = None

    @property
    def cursor_provider(self) -> str:
        return self.token_provider or self.slug


WHOOP_SPEC = SourcePollSpec(
    slug="whoop",
    entrypoint="plugins.sources.whoop:WhoopSource",
    log_label="whoop",
    fetch_error="plugins.sources.whoop.fetch:WhoopFetchError",
)
AMAZFIT_SPEC = SourcePollSpec(
    slug="amazfit",
    entrypoint="plugins.sources.amazfit:AmazfitSource",
    log_label="amazfit",
    fetch_error="plugins.sources.amazfit.fetch:AmazfitFetchError",
)
POLAR_SPEC = SourcePollSpec(
    slug="polar",
    entrypoint="plugins.sources.polar:PolarSource",
    log_label="polar",
    fetch_error="plugins.sources.polar.fetch:PolarFetchError",
    token_provider="polar-accesslink",
)
GOOGLE_HEALTH_SPEC = SourcePollSpec(
    slug="google_health",
    entrypoint="plugins.sources.google_health:GoogleHealthSource",
    log_label="google health",
    fetch_error="plugins.sources.google_health.fetch:GoogleHealthFetchError",
    token_provider="google-health-api",
)


def _plugin_yaml(slug: str) -> Path:
    """Locate a source plugin manifest without hard-coding repo depth."""
    from plugin_sdk import find_plugin_manifest

    return find_plugin_manifest(slug, kind="source", start=Path(__file__))


def _load_entrypoint(entrypoint: str):
    module_name, sep, attr = entrypoint.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError(f"invalid source plugin entrypoint: {entrypoint!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _plugin_lookback(entrypoint: str) -> timedelta | None:
    """The window a plugin fetches when given no ``since`` (its DEFAULT_LOOKBACK)."""
    module = importlib.import_module(entrypoint.partition(":")[0])
    lookback = getattr(module, "DEFAULT_LOOKBACK", None)
    return lookback if isinstance(lookback, timedelta) else None


# A fetch error with one of these statuses says nothing about the window: the
# token is refused (401/403), or the vendor is busy or slow (408/429). A 5xx is
# an outage. Only a 4xx outside this set, or a fetch error with no status (a
# page-cap overflow, a malformed body), is held against a widened window.
_NOT_A_RANGE_FAILURE = frozenset({401, 403, 408, 429})


def is_backfill_range_failure(exc: BaseException, fetch_error: type | None) -> bool:
    """True when a widened poll failed because of its window, not auth or an outage.

    Refresh and auth errors, expired tokens and transport errors are never the
    plugin's fetch error, so a dead token cannot use up the backfill attempts.
    """
    if fetch_error is None or not isinstance(exc, fetch_error):
        return False
    status = getattr(exc, "status_code", None)
    if status is None:
        return True
    return 400 <= status < 500 and status not in _NOT_A_RANGE_FAILURE


def backfill_since(
    last_success: datetime | None,
    *,
    lookback: timedelta | None,
    now: datetime,
) -> datetime | None:
    """The fetch start that covers the gap since ``last_success``.

    None keeps the plugin's default window: no poll has succeeded yet, or the
    default window already reaches back past the last success. Otherwise
    reach back one lookback before the last success (vendors score records
    late, which a healthy run of polls would have re-fetched), bounded by
    :data:`MAX_BACKFILL`.
    """
    if last_success is None or lookback is None or last_success >= now - lookback:
        return None
    return max(last_success - lookback, now - MAX_BACKFILL)


def _has_session_capability(manifest: PluginManifest) -> bool:
    return any(
        capability.record_shape == "session"
        and capability.aggregation_scope == "interval_component"
        for capability in manifest.source_capabilities
    )


async def reconcile_source_poll_sessions(
    session: Any,
    *,
    manifest: PluginManifest,
    fusion_repository: Any = default_fusion_repository,
    owner_id=DEFAULT_OWNER_ID,
    workspace_id=DEFAULT_WORKSPACE_ID,
) -> int:
    """Run reversible session fusion after a source poll.

    This consumes manifest semantics and confirmed device links; it does not
    create identity links or mutate raw observations.
    """

    if not _has_session_capability(manifest):
        return 0

    pairs = await fusion_repository.find_session_candidate_pairs(
        session,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )
    for pair in pairs:
        await fusion_repository.reconcile_session_pair(
            session,
            owner_id=owner_id,
            workspace_id=workspace_id,
            provider_subject_id=pair.provider_subject_id,
            direct=pair.direct,
            relayed=pair.relayed,
            device_link=pair.device_link,
            decided_by=f"source-poll:{manifest.id}",
        )
    return len(pairs)


def make_source_poll(
    session_factory: Any,
    *,
    spec: SourcePollSpec,
    fusion_repository: Any = default_fusion_repository,
) -> Callable[[], Awaitable[None]]:
    """Return an awaitable APScheduler can invoke for one source adapter."""

    async def _run() -> None:
        import httpx
        from plugin_sdk import load_manifest
        from storage.timescale import source_poll_cursors
        from storage.timescale.ingest import PostgresIngestStorage

        manifest = load_manifest(_plugin_yaml(spec.slug))
        plugin_cls = _load_entrypoint(spec.entrypoint)
        plugin = plugin_cls(manifest)
        storage = PostgresIngestStorage()
        polled_at = datetime.now(UTC)

        async with (
            httpx.AsyncClient(timeout=30.0) as http,
            session_factory() as session,
        ):
            widened = False
            unfilled_gap: tuple[datetime, datetime] | None = None
            try:
                payload: dict[str, Any] = {
                    "storage": storage,
                    "session": session,
                    "http_client": http,
                }
                cursor = await source_poll_cursors.get_poll_cursor(
                    session, provider=spec.cursor_provider, owner_id=DEFAULT_OWNER_ID
                )
                lookback = _plugin_lookback(spec.entrypoint)
                since = backfill_since(
                    cursor.last_success_at if cursor is not None else None,
                    lookback=lookback,
                    now=polled_at,
                )
                if since is not None and cursor.backfill_failures >= MAX_BACKFILL_FAILURES:
                    unfilled_gap = (since, polled_at - lookback)
                    log.warning(
                        "%s poll: backfill from %s failed %d times in a row; polling the "
                        "default window instead. %s to %s stays unfilled.",
                        spec.log_label,
                        since.isoformat(),
                        cursor.backfill_failures,
                        unfilled_gap[0].isoformat(),
                        unfilled_gap[1].isoformat(),
                    )
                    since = None
                if since is not None:
                    payload["since"] = since
                    widened = True
                    log.info(
                        "%s poll: last success %s, backfilling from %s",
                        spec.log_label,
                        cursor.last_success_at.isoformat(),
                        since.isoformat(),
                    )
                result = await plugin.ingest(payload)
                if isinstance(result, dict) and result.get(SKIPPED_NO_TOKEN):
                    # Nothing was polled: a skip is not a successful poll.
                    await session.commit()
                    log.info("%s poll skipped: no stored token", spec.log_label)
                    return
                # Same transaction as the poll's data: the cursor never claims
                # a poll whose writes rolled back.
                await source_poll_cursors.record_successful_poll(
                    session,
                    provider=spec.cursor_provider,
                    owner_id=DEFAULT_OWNER_ID,
                    polled_at=polled_at,
                    unfilled_gap=unfilled_gap,
                )
                await session.commit()
                try:
                    reconciled = await reconcile_source_poll_sessions(
                        session,
                        manifest=manifest,
                        fusion_repository=fusion_repository,
                    )
                    if reconciled:
                        await session.commit()
                        log.info(
                            "%s fusion reconciliation: %d candidate pair(s)",
                            spec.log_label,
                            reconciled,
                        )
                except Exception:
                    await session.rollback()
                    log.exception("%s fusion reconciliation failed", spec.log_label)
                log.info("%s poll: %s", spec.log_label, result)
            except Exception as exc:
                await session.rollback()
                log.exception("%s poll failed", spec.log_label)
                fetch_error = _load_entrypoint(spec.fetch_error) if spec.fetch_error else None
                if widened and is_backfill_range_failure(exc, fetch_error):
                    # Count it in its own transaction: the poll's rolled back.
                    try:
                        await source_poll_cursors.record_backfill_failure(
                            session, provider=spec.cursor_provider, owner_id=DEFAULT_OWNER_ID
                        )
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        log.exception("%s: could not record the backfill failure", spec.log_label)
                raise

    return _run


def _register_source_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    spec: SourcePollSpec,
    cron: str,
    job_id: str,
) -> str:
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        make_source_poll(session_factory, spec=spec),
        CronTrigger.from_crontab(cron),
        id=job_id,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    log.info("registered %s cron=%s", job_id, cron)
    return job_id


def make_whoop_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=WHOOP_SPEC)


def register_whoop_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = WHOOP_DEFAULT_CRON,
    job_id: str = "whoop_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=WHOOP_SPEC,
        cron=cron,
        job_id=job_id,
    )


def make_amazfit_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=AMAZFIT_SPEC)


def register_amazfit_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = AMAZFIT_DEFAULT_CRON,
    job_id: str = "amazfit_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=AMAZFIT_SPEC,
        cron=cron,
        job_id=job_id,
    )


def make_polar_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=POLAR_SPEC)


def register_polar_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = POLAR_DEFAULT_CRON,
    job_id: str = "polar_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=POLAR_SPEC,
        cron=cron,
        job_id=job_id,
    )


def make_google_health_poll(session_factory: Any) -> Callable[[], Awaitable[None]]:
    return make_source_poll(session_factory, spec=GOOGLE_HEALTH_SPEC)


def register_google_health_poll(
    scheduler: Any,
    session_factory: Any,
    *,
    cron: str = GOOGLE_HEALTH_DEFAULT_CRON,
    job_id: str = "google_health_poll",
) -> str:
    return _register_source_poll(
        scheduler,
        session_factory,
        spec=GOOGLE_HEALTH_SPEC,
        cron=cron,
        job_id=job_id,
    )

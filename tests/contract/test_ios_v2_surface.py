"""HealthSave iOS-load-bearing v2 surface.

The HealthSave iOS app (App Store ID 6759843047) hardcodes two /api/v2
routes in ``Config.swift`` — it does NOT discover them from
``/api/v2/setup/diagnostics``:

    GET /api/v2/sync/runs/latest          (Config.latestSyncRunEndpoint)
    GET /api/v2/sync/runs/{sync_run_id}   (Config.syncRunEndpoint)

v2 is "free to evolve" by doctrine, but these two routes carry v1-grade
freeze semantics: reshaping or removing them breaks the live App Store
binary's destination receipts immediately. Any failure here is an
iOS-app-breaking change and requires a coordinated App Store release,
not a server change.

The responses are untyped dicts built in
``storage/timescale/sync_receipts.py`` (SQL aliases + literal dict
keys), so there is no Pydantic model to pin. This test pins the keys at
the source level; the golden response corpus
(``tests/fixtures/apple_healthsave_responses/``) pins the executed
bytes.

iOS decoder source of truth:
    ../ios_app/Sources/HealthSync/BackendCompatibility.swift
    (DestinationReceiptClient.decodeLatestReceipt)
Cross-check: ``contracts/IOS_CROSS_CHECK.md``.
"""

from __future__ import annotations

import inspect
import re

from server.main import app
from storage.timescale import sync_receipts

IOS_V2_ROUTES: frozenset[str] = frozenset(
    {
        "GET /api/v2/sync/runs/latest",
        "GET /api/v2/sync/runs/{sync_run_id}",
    }
)

# Keys iOS's decodeLatestReceipt reads from GET /api/v2/sync/runs/latest.
# Emitted by sync_receipts.latest_sync_run as SQL aliases or assigned keys.
IOS_LATEST_RUN_KEYS: frozenset[str] = frozenset(
    {
        "sync_run_id",  # hard requirement: decoder returns nil without it
        "status",
        "records_accepted",
        "records_inserted_new",
        "records_deduped_existing",
        "storage_result_level",
        "records_skipped",  # iOS folds this into recordsRejected
        "batches_seen",
        "batches_processed",
        "completed_at",  # newestReceiptAt fallback chain
        "latest_sample_time",
        "sample_window",
        "metrics",
    }
)

# Keys iOS reads from GET /api/v2/sync/runs/{sync_run_id}. Top-level keys
# plus the nested "summary" object the decoder falls back to.
IOS_SYNC_RUN_KEYS: frozenset[str] = frozenset(
    {
        "sync_run_id",
        "status",
        "verification_level",
        "completed_at",
        "summary",
        "per_metric",
        "records_accepted",
        "records_inserted_new",
        "records_deduped_existing",
        "storage_result_level",
        "records_rejected",
        "batches_seen",
        "batches_processed",
        "sample_window",
        "latest_sample_time",
    }
)

_BREAK_MESSAGE = (
    "HealthSave iOS contract break — this is an iOS-app-breaking change and "
    "requires a coordinated App Store release. The live binary hardcodes the "
    "v2 sync-run surface in Config.swift and decodes these exact keys in "
    "BackendCompatibility.swift::decodeLatestReceipt."
)


def _live_routes() -> frozenset[str]:
    out = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if not path:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            out.add(f"{method} {path}")
    return frozenset(out)


def _emitted_keys(source: str) -> set[str]:
    """Keys a repository function can emit.

    Covers the three styles sync_receipts.py uses: SQL ``AS alias``,
    dict-literal ``"key": value``, and item assignment ``d["key"] = value``.
    """
    aliases = set(re.findall(r"\bAS\s+([a-z_]+)", source))
    literals = set(re.findall(r'"([a-z_]+)":', source))
    assigned = set(re.findall(r'\["([a-z_]+)"\]\s*=', source))
    return aliases | literals | assigned


def test_ios_v2_sync_routes_present() -> None:
    """Both hardcoded iOS v2 routes must always be served."""
    missing = IOS_V2_ROUTES - _live_routes()
    assert not missing, f"missing routes {sorted(missing)}. {_BREAK_MESSAGE}"


def test_latest_route_registered_before_parameterized_route() -> None:
    """/latest must match before /{sync_run_id} captures it as a run id.

    FastAPI matches routes in registration order. If the parameterized
    route ever moves above the literal one, GET /api/v2/sync/runs/latest
    silently becomes a receipt lookup for the run id "latest".
    """
    paths = [getattr(route, "path", "") for route in app.routes]
    latest_idx = paths.index("/api/v2/sync/runs/latest")
    param_idx = paths.index("/api/v2/sync/runs/{sync_run_id}")
    assert latest_idx < param_idx, (
        "/api/v2/sync/runs/latest is registered after the parameterized "
        f"route and will be shadowed. {_BREAK_MESSAGE}"
    )


def test_latest_sync_run_emits_ios_decoder_keys() -> None:
    """latest_sync_run must keep emitting every key iOS decodes."""
    source = inspect.getsource(sync_receipts.latest_sync_run)
    missing = IOS_LATEST_RUN_KEYS - _emitted_keys(source)
    assert not missing, (
        f"storage.timescale.sync_receipts.latest_sync_run no longer emits "
        f"{sorted(missing)}. {_BREAK_MESSAGE}"
    )


def test_sync_run_emits_ios_decoder_keys() -> None:
    """sync_run must keep emitting every key iOS decodes."""
    source = inspect.getsource(sync_receipts.sync_run)
    missing = IOS_SYNC_RUN_KEYS - _emitted_keys(source)
    assert not missing, (
        f"storage.timescale.sync_receipts.sync_run no longer emits "
        f"{sorted(missing)}. {_BREAK_MESSAGE}"
    )


def test_empty_sentinel_status_is_preserved() -> None:
    """The no-receipts response must keep ``"status": "empty"``.

    iOS treats a response whose ``status`` contains "empty" as "no
    receipt yet" and shows nothing. Renaming the sentinel (e.g. to
    "no_data") would make the by-id endpoint's empty response decode as
    a bogus all-zero receipt instead, because it includes sync_run_id.
    """
    for func in (sync_receipts.latest_sync_run, sync_receipts.sync_run):
        source = inspect.getsource(func)
        assert '"status": "empty"' in source, (
            f'{func.__name__} no longer returns the "empty" status sentinel. {_BREAK_MESSAGE}'
        )

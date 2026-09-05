"""Cross-repo mirror invariant: the v2 iOS header manifest in datahub is
byte-equal to the mirror in ios_app/.

Plan 2026-09-03 Slice 5.

This test is the v2 analogue of ``test_ios_headers_in_sync.py``. The
``contracts/v2-ios-headers.json`` file is the canonical home of the
v2 wire header manifest (additive over the frozen v1 manifest in
``contracts/ios-headers.json``). The iOS binary lives in a sibling
repo and the iOS fixture mirror lives at
``ios_app/Tests/HealthSyncTests/Fixtures/v2-ios-headers.json``.

The byte-equal mirror is enforced three ways:
  1. ``tests/contract/api_v2/test_v2_ios_headers.py`` (server consumes
     every header + completeness).
  2. ``V2HeaderContractTests.swift`` (the app's real upload request emits
     exactly these).
  3. THIS test — the two files are byte-equal, so a rename on either
     side fails CI immediately rather than at first-iOS-build.

Skipped when the ios_app/ directory is not checked out alongside datahub
(same convention as ``test_ios_headers_in_sync.py``).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IOS_FIXTURE = (
    REPO_ROOT.parent / "ios_app" / "Tests" / "HealthSyncTests" / "Fixtures" / "v2-ios-headers.json"
)
DATAHUB_CANONICAL = REPO_ROOT / "contracts" / "v2-ios-headers.json"


def test_v2_ios_headers_mirror_is_byte_equal() -> None:
    """The two files are byte-equal.

    Both repositories are first-class wire sources (datahub is the
    response side; ios_app is the request side). A drift here means
    one side has a header the other doesn't see; the contract tests
    on either side catch the symptom but this mirror test catches the
    cause at commit time.
    """
    if not IOS_FIXTURE.exists():
        import pytest

        pytest.skip(
            "ios_app/ not checked out alongside datahub; "
            "v2 ios-headers mirror is verified in iOS CI instead."
        )
    assert DATAHUB_CANONICAL.read_bytes() == IOS_FIXTURE.read_bytes(), (
        "contracts/v2-ios-headers.json (datahub) and "
        "ios_app/Tests/HealthSyncTests/Fixtures/v2-ios-headers.json "
        "are out of sync. The v2 header manifest is a pinned contract; "
        "rename a header on either side and copy the change to the other. "
        "CI on the side that wasn't updated will fail loudly."
    )

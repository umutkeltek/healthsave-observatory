"""``python -m licensing``: the licence checks the ``healthsave`` CLI runs.

    python -m licensing show [--file PATH]           describe a licence
    python -m licensing check FEATURE [--file PATH]  is FEATURE allowed now?

``--file -`` reads the licence from stdin, so the CLI can run the same check on
the host or inside the Observatory image. Without ``--file`` the installed
licence is used (see :func:`licensing.license_path`).

Exit codes: 0 usable / allowed, 1 refused (the reason is on stderr), 2 usage.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime

from .verify import (
    KNOWN_FEATURES,
    License,
    LicenseError,
    LicenseState,
    check_feature,
    license_path,
    load_license_file,
    parse_license,
)

_MAX_STDIN_BYTES = 64 * 1024


def _load(file: str | None) -> License:
    if file == "-":
        return parse_license(sys.stdin.read(_MAX_STDIN_BYTES))
    return load_license_file(license_path() if file is None else file)


def _day(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")


def _status_line(license: License) -> str:
    state = license.state()
    if state is LicenseState.ACTIVE:
        return f"active until {_day(license.expires_at)}"
    if state is LicenseState.GRACE:
        return (
            f"in grace period: expired {_day(license.expires_at)}, "
            f"features keep working until {_day(license.grace_ends_at)}"
        )
    return f"expired {_day(license.expires_at)}, grace period ended {_day(license.grace_ends_at)}"


def _show(file: str | None) -> int:
    license = _load(file)
    features = ", ".join(license.features) if license.features else "(none)"
    print(f"Tier:      {license.tier}")
    print(f"Status:    {_status_line(license)}")
    print(f"Seats:     {license.seats}")
    print(f"Features:  {features}")
    print(f"Customer:  {license.sub}")
    print(f"Issued:    {_day(license.issued_at)}")
    if license.state() is LicenseState.EXPIRED:
        print(
            "This licence has expired. Renew it to use Care features again; "
            "free features keep working.",
            file=sys.stderr,
        )
        return 1
    return 0


def _check(feature: str, file: str | None) -> int:
    license = check_feature(_load(file), feature)
    if license.state() is LicenseState.GRACE:
        print(
            f"Note: the {license.tier} licence expired on {_day(license.expires_at)}; "
            f"its features keep working until {_day(license.grace_ends_at)}. Renew to keep them.",
            file=sys.stderr,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m licensing", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show", help="describe a licence; exit 0 if it is usable")
    show.add_argument("--file", help="licence file, or - for stdin")
    check = sub.add_parser("check", help="exit 0 if FEATURE is allowed now")
    check.add_argument("feature", choices=sorted(KNOWN_FEATURES))
    check.add_argument("--file", help="licence file, or - for stdin")
    args = parser.parse_args(argv)
    try:
        if args.command == "show":
            return _show(args.file)
        return _check(args.feature, args.file)
    except LicenseError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

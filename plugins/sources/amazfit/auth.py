"""Zepp / Amazfit token-import helpers (H-revise — 2026-05-22).

The two-step ``v2/client/login`` MD5-password flow this module
originally shipped (P6-a, commit ``a3525d8``) **no longer works**.
On 2026-05-22 a verification probe showed step-1 returning ``HTTP
400 {"error_code":"0100"}`` for valid credentials, and the legacy
``apps-vm-scheduler-1`` Amazfit poll had been silently 500-ing
hourly for at least 13 consecutive hours against the same flow.

The community-converged replacement (huami-token issue #119,
zepp-health-cli) is: do NOT carry plaintext passwords inside the
datahub at all. Operators obtain an ``app_token`` via the
externally-maintained ``huami-token`` PyPI CLI (or by capturing
the Zepp app's traffic via a proxy) and hand that token to our
authorize CLI. The plugin's persistence + worker poll surfaces
stay identical to Whoop's — we just don't own the auth boundary
any more.

This module exposes pure helpers that turn an externally-acquired
``app_token`` (plus ``user_id`` + region) into the project's
shared :class:`OAuthToken` shape so it can be persisted via the
same ``storage.timescale.oauth_tokens`` repo Whoop uses (provider
``"amazfit"``). Persistence is delegated to the authorize CLI;
this module never touches the DB.

Why no refresh primitive? Zepp does not issue refresh tokens in
the ``v2/registrations/tokens`` flow that's currently working
upstream. The huami-token CLI re-derives a fresh ``app_token``
each invocation from the operator's account password. On token
expiry, the worker fails loud and the operator re-runs the
huami-token CLI + our authorize CLI. By design — keeps the
plaintext password OUT of long-running services entirely.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from auth import DEFAULT_OWNER_ID, OAuthToken

from . import PROVIDER, REGION_BASE_URLS

ENV_APP_TOKEN = "AMAZFIT_APP_TOKEN"
ENV_USER_ID = "AMAZFIT_USER_ID"
ENV_REGION = "AMAZFIT_REGION"

# Live probe (2026-05-22) surfaced an ``expiration`` claim of ~11 days
# from the huami-token issuance flow. We hedge SHORTER (10 days) so the
# worker trips the fail-loud expiry path BEFORE Zepp's real expiration
# kicks in — otherwise the worker would silently 401 for 14+ days
# against an actually-dead token while still claiming "not expired"
# locally. The whole point of fail-loud expiry is operator awareness;
# hedging longer than upstream defeats it.
DEFAULT_TOKEN_TTL = timedelta(days=10)


class AmazfitAuthError(Exception):
    """Raised when token import inputs are missing or malformed."""


@dataclass(frozen=True, slots=True)
class AmazfitClientConfig:
    """Operator-supplied non-secret region selector.

    The deprecated v2/client/login flow required email + password in
    config; the current import flow only needs region so the fetchers
    can pick the right ``api-mifit-*.zepp.com`` host. The secret
    (``app_token``) is read from env separately by
    :func:`token_from_env` and never persisted in this dataclass.
    """

    region: str = "us"

    @property
    def base_url(self) -> str:
        """Region-keyed base URL for the Zepp data API.

        Unknown regions fall back to the US host rather than raising, giving
        operators a single obvious endpoint to inspect when a region is
        mistyped.
        """
        return REGION_BASE_URLS.get(self.region, REGION_BASE_URLS["us"])

    @classmethod
    def from_env(cls) -> AmazfitClientConfig:
        region = os.environ.get(ENV_REGION, "us").lower()
        return cls(region=region)


# Regexes that match the format huami-token >=0.8.0 emits when run
# with ``--no_logout``. The CLI prints a banner ``No logout!`` then
# two ``key=value`` lines (``app_token`` first, then ``login_token``).
# The user id surfaces earlier in an INFO log line that ends with
# ``User id: <digits>``. The parser is intentionally forgiving so an
# upstream cosmetic logger tweak (e.g. extra timestamps) does not
# break us — we anchor on the literal field name + ``=`` / ``: ``.
_APP_TOKEN_RE = re.compile(r"^app_token=(\S+)\s*$", re.MULTILINE)
_USER_ID_RE = re.compile(r"User id:\s*(\d+)")


def token_from_app_token_string(
    *,
    access_token: str,
    user_id: str,
    region: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """Wrap an operator-supplied app_token into an :class:`OAuthToken`.

    Used by the authorize CLI's ``--from-token`` mode. ``user_id`` is
    persisted in the token's ``metadata`` so the fetch loop can route
    ``/users/<user_id>/...`` paths without reloading config.
    """
    access_token = (access_token or "").strip()
    user_id = (user_id or "").strip()
    region = (region or "us").strip().lower()
    if not access_token:
        raise AmazfitAuthError("access_token is empty")
    if not user_id.isdigit():
        raise AmazfitAuthError(f"user_id must be all-digits: {user_id!r}")

    base_url = REGION_BASE_URLS.get(region, REGION_BASE_URLS["us"])
    return OAuthToken(
        owner_id=owner_id,
        provider=PROVIDER,
        access_token=access_token,
        refresh_token=None,
        expires_at=datetime.now(UTC) + DEFAULT_TOKEN_TTL,
        scopes=(),
        metadata={
            "base_url": base_url,
            "region": region,
            "user_id": user_id,
        },
    )


def token_from_huami_token_output(
    output_text: str,
    *,
    region: str = "us",
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """Parse huami-token CLI's stdout into an :class:`OAuthToken`.

    Expected to be called with the captured output of:

      huami-token --method amazfit -e <email> -p <pw> --no_logout

    The CLI prints a banner block whose two load-bearing lines are::

        app_token=<base64-ish blob>
        login_token=<base64-ish blob>

    plus an earlier INFO line ending in ``User id: <digits>``. We
    don't care about ``login_token`` — it's an intermediate value
    used during the CLI's own flow; the data API only needs
    ``app_token`` + ``user_id``.

    ``region`` is operator-supplied (the CLI does not echo a
    canonical region; the AWS-style ``us-west-2`` value that appears
    in its debug log is the S3 redirect's AWS region, not the data
    API region). Use ``us`` / ``eu`` / ``cn``.
    """
    if not output_text or not output_text.strip():
        raise AmazfitAuthError("huami-token output is empty")

    app_token_match = _APP_TOKEN_RE.search(output_text)
    if not app_token_match:
        raise AmazfitAuthError("could not find an 'app_token=<value>' line in huami-token output")
    user_id_match = _USER_ID_RE.search(output_text)
    if not user_id_match:
        raise AmazfitAuthError("could not find 'User id: <digits>' in huami-token output")

    return token_from_app_token_string(
        access_token=app_token_match.group(1),
        user_id=user_id_match.group(1),
        region=region,
        owner_id=owner_id,
    )


def token_from_env(
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> OAuthToken:
    """Materialize a token from ``AMAZFIT_APP_TOKEN`` + ``AMAZFIT_USER_ID`` env.

    Convenience for CLI invocations that prefer env vars to flags.
    Region defaults to ``AMAZFIT_REGION`` or ``us``.
    """
    access_token = os.environ.get(ENV_APP_TOKEN, "")
    user_id = os.environ.get(ENV_USER_ID, "")
    region = os.environ.get(ENV_REGION, "us")
    missing = [k for k, v in ((ENV_APP_TOKEN, access_token), (ENV_USER_ID, user_id)) if not v]
    if missing:
        raise AmazfitAuthError(f"missing required Amazfit env vars: {', '.join(missing)}")
    return token_from_app_token_string(
        access_token=access_token,
        user_id=user_id,
        region=region,
        owner_id=owner_id,
    )

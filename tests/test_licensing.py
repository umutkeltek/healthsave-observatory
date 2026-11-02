"""The licensing package: offline Ed25519 verification, expiry, grace, tamper."""

from __future__ import annotations

import ast
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import licensing
import pytest
from cryptography.hazmat.primitives import serialization
from licensing import (
    FeatureNotLicensed,
    LicenseExpired,
    LicenseInvalid,
    LicenseNotFound,
    LicenseState,
    current_license,
    parse_license,
    require_feature,
)
from licensing import keys as licence_keys
from licensing.__main__ import main as licensing_main
from licensing.verify import canonical_payload

from tests.licence_testkit import ROOT, TestKey, expired, make_key, mint, payload

# The production verification key, as given by the billing side (2026-11-02).
PRODUCTION_KEY_B64URL = "39wLoA2bkHC1G6MSHJRmdWUIqvSNT4TQZFDwq9_fres"
PRODUCTION_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEA39wLoA2bkHC1G6MSHJRmdWUIqvSNT4TQZFDwq9/fres=\n"
    "-----END PUBLIC KEY-----\n"
)


@pytest.fixture
def key(monkeypatch) -> TestKey:
    test_key = make_key()
    monkeypatch.setattr(licence_keys, "PUBLIC_KEY_B64URL", test_key.public_b64url)
    return test_key


def _segments(token: str) -> tuple[bytes, bytes]:
    payload_part, signature_part = token.split(".")
    pad = lambda part: part + "=" * (-len(part) % 4)  # noqa: E731
    return base64.urlsafe_b64decode(pad(payload_part)), base64.urlsafe_b64decode(
        pad(signature_part)
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# --- the embedded key -------------------------------------------------------


def test_embedded_key_is_the_production_key():
    assert licence_keys.PUBLIC_KEY_B64URL == PRODUCTION_KEY_B64URL
    pem = (
        licensing.embedded_public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    assert pem == PRODUCTION_KEY_PEM


def test_a_test_signed_licence_is_rejected_by_the_production_key():
    token = mint(make_key())
    with pytest.raises(LicenseInvalid, match="signature does not match"):
        parse_license(token)


# --- verify -----------------------------------------------------------------


def test_valid_licence_round_trips(key):
    lic = parse_license(mint(key) + "\n")
    assert lic.tier == "care"
    assert lic.seats == 1
    assert lic.features == ("care.backup.offsite", "care.restore.drill", "care.update.rollback")
    assert lic.sub == "ctm_test_customer"
    assert lic.expires_at.tzinfo is not None
    assert lic.state() is LicenseState.ACTIVE


def test_signature_covers_the_canonical_payload_bytes(key):
    data = payload()
    payload_bytes, _ = _segments(mint(key))
    assert payload_bytes == canonical_payload(data)
    assert payload_bytes == json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def test_padded_base64url_is_accepted(key):
    payload_bytes, signature = _segments(mint(key))
    padded = (
        base64.urlsafe_b64encode(payload_bytes).decode()
        + "."
        + base64.urlsafe_b64encode(signature).decode()
    )
    assert parse_license(padded).tier == "care"


def test_tampered_payload_is_rejected(key):
    payload_bytes, signature = _segments(mint(key))
    longer = payload_bytes.replace(b'"exp":"', b'"exp":"2', 1)  # push expiry ~1000 years out
    data = json.loads(payload_bytes)
    data["exp"] = "2999-01-01T00:00:00Z"
    for forged in (longer, canonical_payload(data)):
        with pytest.raises(LicenseInvalid, match="signature does not match"):
            parse_license(f"{_b64(forged)}.{_b64(signature)}")


def test_flipped_signature_bit_is_rejected(key):
    payload_bytes, signature = _segments(mint(key))
    broken = bytes([signature[0] ^ 1]) + signature[1:]
    with pytest.raises(LicenseInvalid, match="signature does not match"):
        parse_license(f"{_b64(payload_bytes)}.{_b64(broken)}")


def test_licence_from_another_key_is_rejected(key):
    with pytest.raises(LicenseInvalid, match="signature does not match"):
        parse_license(mint(make_key()))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not-a-licence",
        "a.b.c",
        "abc.",
        ".abc",
        "ab$c.def",
        "YWJj.YWJj",  # signature too short
        "YW Jj." + "A" * 86,
    ],
)
def test_malformed_files_are_rejected(text):
    with pytest.raises(LicenseInvalid):
        parse_license(text)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"v": 2}, "format 2"),
        ({"v": True}, "format True"),
        ({"tier": "gold"}, "unknown tier"),
        ({"sub": ""}, "customer id"),
        ({"email_sha256": "not-hex"}, "email hash"),
        ({"seats": 0}, "seat count"),
        ({"seats": "1"}, "seat count"),
        ({"features": "care.backup.offsite"}, "feature list"),
        ({"features": [""]}, "feature list"),
        ({"nonce": ""}, "nonce"),
        ({"iat": "2026-11-02T10:00:00"}, "time zone"),
        ({"exp": "next year"}, "malformed exp"),
        ({"exp": 1735689600}, "no exp"),
        ({"iat": "2027-01-01T00:00:00Z", "exp": "2026-01-01T00:00:00Z"}, "before it was issued"),
    ],
)
def test_signed_but_malformed_payloads_are_rejected(key, overrides, message):
    data = payload(**overrides)
    body = canonical_payload(data)
    token = f"{_b64(body)}.{_b64(key.private_key.sign(body))}"
    with pytest.raises(LicenseInvalid, match=message):
        parse_license(token)


def test_signed_non_object_payload_is_rejected(key):
    body = b"[1,2,3]"
    with pytest.raises(LicenseInvalid, match="not an object"):
        parse_license(f"{_b64(body)}.{_b64(key.private_key.sign(body))}")


def test_unknown_payload_keys_and_features_are_kept_for_forward_compatibility(key):
    lic = parse_license(mint(key, features=["care.backup.offsite", "care.future.thing"], extra=1))
    assert lic.includes("care.future.thing")


def test_non_utc_offsets_are_normalised_to_utc(key):
    lic = parse_license(mint(key, exp="2030-01-01T02:00:00+02:00"))
    assert lic.expires_at == datetime(2030, 1, 1, tzinfo=UTC)


# --- expiry and grace -------------------------------------------------------


def test_state_moves_active_then_grace_then_expired(key):
    lic = parse_license(mint(key, exp="2030-01-01T00:00:00Z"))
    exp = datetime(2030, 1, 1, tzinfo=UTC)
    assert lic.state(exp) is LicenseState.ACTIVE
    assert lic.state(exp + timedelta(seconds=1)) is LicenseState.GRACE
    assert lic.state(exp + timedelta(days=14)) is LicenseState.GRACE
    assert lic.state(exp + timedelta(days=14, seconds=1)) is LicenseState.EXPIRED
    assert lic.grace_ends_at == exp + timedelta(days=14)


def test_require_feature_allows_during_grace(key, tmp_path):
    file = tmp_path / "healthsave.license"
    file.write_text(mint(key, **expired(days_ago=3)))
    lic = require_feature("care.backup.offsite", path=file)
    assert lic.state() is LicenseState.GRACE


def test_require_feature_refuses_after_grace(key, tmp_path):
    file = tmp_path / "healthsave.license"
    file.write_text(mint(key, **expired(days_ago=15)))
    with pytest.raises(LicenseExpired, match="grace period ended") as err:
        require_feature("care.backup.offsite", path=file)
    assert err.value.license.tier == "care"


def test_require_feature_refuses_a_feature_the_licence_lacks(key, tmp_path):
    file = tmp_path / "healthsave.license"
    file.write_text(mint(key, features=["care.restore.drill"]))
    with pytest.raises(FeatureNotLicensed, match="does not include care.backup.offsite"):
        require_feature("care.backup.offsite", path=file)
    assert require_feature("care.restore.drill", path=file).tier == "care"


def test_require_feature_without_a_licence_raises_not_found(tmp_path):
    with pytest.raises(LicenseNotFound):
        require_feature("care.backup.offsite", path=tmp_path / "healthsave.license")


def test_require_feature_rejects_unknown_feature_names(tmp_path):
    with pytest.raises(ValueError, match="unknown licence feature"):
        require_feature("care.backup.offsight", path=tmp_path / "x")


def test_errors_share_one_base_class():
    for error in (LicenseNotFound, LicenseInvalid, LicenseExpired, FeatureNotLicensed):
        assert issubclass(error, licensing.LicenseError)


# --- where the file lives ---------------------------------------------------


def test_current_license_is_none_without_a_file(tmp_path, monkeypatch):
    monkeypatch.delenv("HEALTHSAVE_LICENSE_FILE", raising=False)
    monkeypatch.delenv("ANALYSIS_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert current_license() is None


def test_current_license_raises_for_a_tampered_file(key, tmp_path):
    file = tmp_path / "healthsave.license"
    file.write_text(mint(key)[:-4] + "AAAA")
    with pytest.raises(LicenseInvalid):
        current_license(file)


def test_licence_lives_next_to_config_yaml(key, tmp_path, monkeypatch):
    monkeypatch.delenv("HEALTHSAVE_LICENSE_FILE", raising=False)
    monkeypatch.delenv("ANALYSIS_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert licensing.license_path() == tmp_path / "healthsave.license"
    (tmp_path / "healthsave.license").write_text(mint(key))
    assert current_license().tier == "care"

    config_dir = tmp_path / "etc"
    config_dir.mkdir()
    monkeypatch.setenv("ANALYSIS_CONFIG", str(config_dir / "config.yaml"))
    assert licensing.license_path() == config_dir / "healthsave.license"

    monkeypatch.setenv("HEALTHSAVE_LICENSE_FILE", str(tmp_path / "elsewhere.license"))
    assert licensing.license_path() == tmp_path / "elsewhere.license"


# --- python -m licensing ----------------------------------------------------


def test_module_cli_show_and_check(key, tmp_path, capsys):
    file = tmp_path / "healthsave.license"
    file.write_text(mint(key, features=["care.restore.drill"]))
    assert licensing_main(["show", "--file", str(file)]) == 0
    out = capsys.readouterr().out
    assert "Tier:      care" in out
    assert "active until" in out
    assert licensing_main(["check", "care.restore.drill", "--file", str(file)]) == 0
    assert licensing_main(["check", "care.backup.offsite", "--file", str(file)]) == 1
    assert "does not include care.backup.offsite" in capsys.readouterr().err


def test_module_cli_reads_stdin(key, monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(mint(key, **expired(days_ago=2))))
    assert licensing_main(["check", "care.update.rollback", "--file", "-"]) == 0
    assert "keep working until" in capsys.readouterr().err


def test_module_cli_refuses_expired_and_missing(key, tmp_path, capsys):
    file = tmp_path / "healthsave.license"
    file.write_text(mint(key, **expired(days_ago=30)))
    assert licensing_main(["show", "--file", str(file)]) == 1
    assert licensing_main(["check", "care.backup.offsite", "--file", str(file)]) == 1
    assert licensing_main(["show", "--file", str(tmp_path / "missing")]) == 1
    assert "No licence file" in capsys.readouterr().err


# --- no phone-home ----------------------------------------------------------

NETWORK_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "httpx",
    "requests",
    "aiohttp",
    "ftplib",
    "smtplib",
    "asyncio",
}


def test_licensing_package_never_imports_network_modules():
    package = ROOT / "packages" / "py" / "licensing"
    files = sorted(package.glob("*.py"))
    assert files
    for path in files:
        tree = ast.parse(Path(path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in NETWORK_MODULES, f"{path.name} imports {name}"


def test_licensing_is_packaged_for_the_image_and_the_wheel():
    # Failure mode 10: a package that passes pytest but is missing from the image.
    assert "COPY packages/py/licensing/ ./licensing/" in (ROOT / "Dockerfile").read_text()
    assert '"licensing*"' in (ROOT / "pyproject.toml").read_text()


# --- cross-implementation golden file ----------------------------------------

REFERENCE = ROOT / "tests" / "fixtures" / "licensing" / "reference-care-expired.license"


def test_billing_worker_licence_verifies_with_the_embedded_key():
    # Signed 2026-11-02 by the billing worker's own signLicense() with the real
    # production key. It expired 2026-01-02, so committing it unlocks nothing.
    text = REFERENCE.read_text()
    lic = parse_license(text)
    assert lic.tier == "care"
    assert lic.sub == "reference-fixture-not-a-customer"
    assert lic.features == ("care.backup.offsite", "care.restore.drill", "care.update.rollback")
    assert lic.issued_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert lic.expires_at == datetime(2026, 1, 2, tzinfo=UTC)
    assert lic.state() is LicenseState.EXPIRED
    with pytest.raises(LicenseExpired):
        licensing.check_feature(lic, "care.backup.offsite")

    # Both sides serialise the payload identically (sorted keys, no whitespace,
    # unpadded base64url), so a licence minted here is byte-compatible too.
    payload_part, signature_part = text.strip().split(".")
    assert "=" not in payload_part + signature_part
    payload_bytes, _ = _segments(text.strip())
    assert canonical_payload(json.loads(payload_bytes)) == payload_bytes


def test_billing_worker_licence_survives_pasting_with_whitespace_and_padding():
    payload_bytes, signature = _segments(REFERENCE.read_text().strip())
    pasted = (
        "\n  "
        + base64.urlsafe_b64encode(payload_bytes).decode()
        + "."
        + base64.urlsafe_b64encode(signature).decode()
        + "  \r\n"
    )
    assert parse_license(pasted).sub == "reference-fixture-not-a-customer"

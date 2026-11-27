"""scripts/license_keygen.py and scripts/license_sign.py mint test licences."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from licensing import parse_license
from licensing.verify import canonical_payload

from scripts import license_keygen, license_sign
from tests.licence_testkit import ROOT, payload


def _run(script: str, *args: str, env: dict[str, str] | None = None, stdin: str | None = None):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        env={**os.environ, **(env or {})},
        input=stdin,
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_keygen_writes_a_private_key_outside_the_repo(tmp_path):
    target = tmp_path / "test-signing.pem"
    proc = _run("license_keygen.py", str(target))
    assert proc.returncode == 0, proc.stderr
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
    public_b64url = proc.stdout.splitlines()[2]
    assert len(public_b64url) == 43
    assert "BEGIN PRIVATE KEY" not in proc.stdout


def test_keygen_refuses_the_repo_and_existing_files(tmp_path):
    inside = ROOT / "packages" / "py" / "licensing" / "never.pem"
    proc = _run("license_keygen.py", str(inside))
    assert proc.returncode == 1
    assert "inside the repository" in proc.stderr
    assert not inside.exists()

    existing = tmp_path / "taken.pem"
    existing.write_text("keep me")
    proc = _run("license_keygen.py", str(existing))
    assert proc.returncode == 1
    assert existing.read_text() == "keep me"


def test_sign_with_a_key_from_the_env_produces_a_verifiable_licence(tmp_path):
    key_path = tmp_path / "k.pem"
    keygen = _run("license_keygen.py", str(key_path))
    public_b64url = keygen.stdout.splitlines()[2]
    body = {k: v for k, v in payload().items() if k not in {"v", "iat", "exp", "nonce"}}
    (tmp_path / "payload.json").write_text(json.dumps(body))
    out = tmp_path / "test.license"

    proc = _run(
        "license_sign.py",
        str(tmp_path / "payload.json"),
        "--days",
        "30",
        "--out",
        str(out),
        env={"HEALTHSAVE_LICENSE_SIGNING_KEY": str(key_path)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "not the one embedded" in proc.stderr  # a test key, so the build would refuse it
    assert out.stat().st_mode & 0o777 == 0o600
    key = license_sign.load_private_key(key_path.read_bytes())
    lic = parse_license(out.read_text(), public_key=key.public_key())
    assert lic.tier == "care"
    assert (lic.expires_at - lic.issued_at).days == 30
    assert public_b64url in keygen.stdout


def test_sign_needs_a_key(tmp_path):
    (tmp_path / "p.json").write_text(json.dumps(payload()))
    env = {k: v for k, v in os.environ.items() if k != "HEALTHSAVE_LICENSE_SIGNING_KEY"}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "license_sign.py"), str(tmp_path / "p.json")],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "HEALTHSAVE_LICENSE_SIGNING_KEY" in proc.stderr


def test_sign_refuses_a_malformed_payload(tmp_path):
    key_path = tmp_path / "k.pem"
    _run("license_keygen.py", str(key_path))
    proc = _run(
        "license_sign.py",
        "-",
        env={"HEALTHSAVE_LICENSE_SIGNING_KEY": str(key_path)},
        stdin=json.dumps(payload(tier="platinum")),
    )
    assert proc.returncode == 1
    assert "unknown tier" in proc.stderr
    assert proc.stdout == ""


def test_complete_payload_fills_defaults_and_needs_exp():
    body = {"tier": "care", "sub": "x", "email_sha256": "0" * 64, "seats": 1, "features": []}
    with pytest.raises(ValueError, match="--days"):
        license_sign.complete_payload(body)
    filled = license_sign.complete_payload(body, days=1)
    assert filled["v"] == 1
    assert filled["iat"].endswith("Z") and filled["exp"].endswith("Z")
    assert len(filled["nonce"]) == 22  # 16 bytes, base64url without padding
    assert canonical_payload(filled).startswith(b'{"email_sha256":')


def test_keychain_reader_accepts_the_hex_form_security_prints(monkeypatch):
    private_pem, _, _ = license_keygen.generate_keypair()
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=private_pem.hex() + "\n", stderr="")

    monkeypatch.setattr(license_sign.subprocess, "run", fake_run)
    key = license_sign.private_key_from_keychain()
    assert calls == [
        [
            "security",
            "find-generic-password",
            "-s",
            "healthsave-licence-signing-key",
            "-a",
            "ed25519-pkcs8-pem",
            "-w",
        ]
    ]
    assert license_sign.load_private_key(private_pem).public_key().public_bytes_raw() == (
        key.public_key().public_bytes_raw()
    )


def test_keychain_reader_reports_a_missing_item_without_output(monkeypatch):
    monkeypatch.setattr(
        license_sign.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=44, stdout="", stderr="not found"),
    )
    with pytest.raises(ValueError, match="no Keychain item"):
        license_sign.private_key_from_keychain()

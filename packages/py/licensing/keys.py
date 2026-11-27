"""The public half of the HealthSave licence signing key.

Every licence file is checked against this key, on this machine. The private
half never enters this repository: it lives with the billing service that
issues licences. ``scripts/license_keygen.py`` makes throwaway keypairs for
tests only; replacing this constant with one of those would make every real
licence fail to verify (``tests/test_licensing.py`` pins the value).
"""

from __future__ import annotations

# Raw 32-byte Ed25519 public key, base64url without padding. The same key as
# SubjectPublicKeyInfo PEM:
#   -----BEGIN PUBLIC KEY-----
#   MCowBQYDK2VwAyEA39wLoA2bkHC1G6MSHJRmdWUIqvSNT4TQZFDwq9/fres=
#   -----END PUBLIC KEY-----
PUBLIC_KEY_B64URL = "39wLoA2bkHC1G6MSHJRmdWUIqvSNT4TQZFDwq9_fres"

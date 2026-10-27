# Security policy

HealthSave Observatory stores health data on hardware you control. If you find a
way to read, change or leak that data without the API key, or to get data out
of the box past the [egress boundary](docs/concepts/privacy-and-egress.md),
please tell us privately before you tell anyone else.

## Report a vulnerability

Email **support@healthsave.app** with `SECURITY` in the subject. Please include:

- the Observatory version (`healthsave version`, or the release tag you run)
- what an attacker needs (network position, a key, local access)
- steps to reproduce, and what you saw happen

Please do not open a public GitHub issue for a vulnerability, and do not test
against an Observatory you don't own.

HealthSave is maintained by one person. You will get a human reply, usually
within a few days. Once a fix is released we credit you in the
[changelog](CHANGELOG.md) unless you would rather not be named.

## Supported versions

Fixes land on `main` and ship in the next tagged release. Only the newest
release is supported: upgrade with the steps in [UPGRADING.md](UPGRADING.md).

## Scope

In scope: the API, the Observatory web app, the `healthsave` CLI and installers,
the bundled Docker Compose stack, and the plugins in this repository.

Also welcome: anything about the HealthSave iOS or Android app's connection to
an Observatory (pairing, API keys, sync). Send those to the same address.

How the system is meant to be secured, and the known limits today, are in
[docs/operations/security.md](docs/operations/security.md).

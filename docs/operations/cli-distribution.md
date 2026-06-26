# CLI Distribution

HealthSave has one public command: `healthsave`.

Package managers install a thin bootstrapper. Stack operations live in the checkout-local `./healthsave` launcher, so npm, npx, future Homebrew, and manual checkout all delegate to the same setup, layer control, web/Grafana/MQTT logic, doctor checks, logs, and verification.

## Human Commands

Install once:

```bash
npm i -g healthsave
healthsave onboard
```

No global install:

```bash
npx healthsave
```

Both commands open the guided onboarding/control center. Users should not need to type a long setup command for the normal path.

## npm / npx

Implemented package:

- npm package: `healthsave`
- primary binary: `healthsave`
- alias binary: `healthsave-observatory`
- package source: `packages/npm/healthsave-observatory`

The npm bootstrapper:

1. Finds an existing checkout from the current directory upward.
2. Uses `HEALTHSAVE_OBSERVATORY_HOME` or `~/healthsave-observatory` when no checkout is found.
3. Clones `https://github.com/umutkeltek/healthsave-observatory.git` when the checkout is missing.
4. Checks out the package release ref for new checkouts.
5. Delegates to checkout-local `./healthsave`.

Package-manager installs own the public `healthsave` command. A checkout-local wrapper is explicit and mainly for manual checkouts.

Version checks:

```bash
healthsave --version
healthsave version --json
./healthsave version
```

Uninstall the global npm package:

```bash
npm uninstall -g healthsave
```

Remove a checkout-local wrapper:

```bash
healthsave uninstall-cli
```

Neither command removes the checkout directory, running containers, Docker volumes, configuration, or health data.

## Scriptable Commands

Agents, CI, and remote automation should use named commands:

```bash
set -euo pipefail
healthsave setup basic --no-input
healthsave doctor --json
healthsave status --json
healthsave layers --json
healthsave logs api
```

No-install automation on a clean machine:

```bash
npx --yes healthsave setup basic --no-input
```

That command belongs in automation docs. It should not be the main human install experience.

## Local Verification Before npm Publish

From the repository root:

```bash
set -euo pipefail
node --check packages/npm/healthsave-observatory/bin/healthsave-observatory.mjs
uv run --extra dev python -m pytest -q tests/test_npx_cli.py tests/test_healthsave_cli.py
```

From the npm package directory:

```bash
set -euo pipefail
npm pack --dry-run
npm publish --dry-run
```

Smoke test from outside the repository:

```bash
npx --yes --package ./packages/npm/healthsave-observatory healthsave --version
```

Publish checklist:

```bash
set -euo pipefail
npm login
npm publish --access public
test "$(npm view healthsave@0.1.3 version)" = "0.1.3"
npx --yes healthsave@0.1.3 --version
```

Before publishing, run the verification suite and scan the diff for secrets.

## Repo-Local Launcher

Manual checkout works without npm:

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave onboard
```

`./healthsave` is the product-owned launcher. Package-manager wrappers call it after they create or find a checkout.

## Local Wrapper

After checkout exists:

```bash
./healthsave install-cli
healthsave doctor
```

This installs a small wrapper into `~/.local/bin` that calls checkout-local `./healthsave`. It avoids sudo and keeps stack operation independent from npm global state.

## Homebrew

Homebrew is the planned macOS/Linux package-manager path after tagged GitHub release artifacts exist. The formula should install the same bootstrapper, not a second setup implementation.

Target flow:

```bash
brew tap healthsave/observatory && brew install healthsave && healthsave onboard
```

Required before enabling the tap:

- GitHub release tag tarball checksum.
- Formula installs `healthsave` and `healthsave-observatory`.
- `brew test healthsave` runs `healthsave --version` and `healthsave --help`.
- Upgrade behavior preserves existing stack directories.

Formula template: `packaging/homebrew/healthsave.rb.template`.

## Platform Notes

- macOS: installer, npm/npx, repo-local launcher, local wrapper, and future Homebrew are viable.
- Linux: installer, npm/npx, repo-local launcher, and local wrapper are primary.
- WSL2: supported with Docker Desktop WSL integration; run npm/npx and `healthsave` inside WSL2.
- Native Windows: PowerShell installer is a WSL2 handoff today, not a native Docker Compose install.
- Termux: unsupported because Docker Compose is required.

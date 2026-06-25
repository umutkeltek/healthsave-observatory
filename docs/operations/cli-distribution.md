# CLI Distribution

HealthSave Observatory keeps one command contract: `healthsave`.

Package managers may bootstrap or install it, but Docker Compose setup, layer
control, Grafana/web/MQTT logic, and verification stay in the checkout-local
`./healthsave` CLI.

## npm / npx

Implemented in this repo under `packages/npm/healthsave-observatory`.
In the local HealthSave product workspace, that path is
`datahub/packages/npm/healthsave-observatory` because `datahub/` is the
Observatory repository.

Public flow after the npm package is published:

```bash
npx healthsave setup basic ~/healthsave-observatory
healthsave doctor
healthsave tui
```

Advanced setup:

```bash
npx healthsave setup advanced ~/healthsave-observatory
```

The npm package name is `healthsave`. It installs two binaries:

- `healthsave` - primary user command.
- `healthsave-observatory` - longer alias for disambiguation.

The npm package is a thin bootstrapper. It clones or reuses
`https://github.com/umutkeltek/healthsave-observatory.git`, installs the local
wrapper when possible, then delegates to the checkout's `./healthsave`.

`healthsave tui` is the interactive human surface. It uses arrow keys and Enter
for setup, stack control, optional layer toggles, doctor/status, logs,
verification, and CLI installation. Scriptable subcommands remain the automation
surface for agents and CI.

Local verification before publish:

```bash
npm exec --yes --package ./packages/npm/healthsave-observatory -- healthsave --version
npx --yes --package ./packages/npm/healthsave-observatory healthsave layers --dir "$PWD" --json
npm pack --dry-run
```

Publish checklist:

```bash
# From the HealthSave product workspace:
cd datahub/packages/npm/healthsave-observatory

# From a standalone healthsave-observatory checkout:
# cd packages/npm/healthsave-observatory

npm login
npm publish --access public
npm view healthsave name version
npx --yes healthsave --version
```

Do not publish until `./healthsave verify`, package tests, and
`npm pack --dry-run` pass.

## Repo-Local Launcher

Works from a checkout without npm:

```bash
git clone https://github.com/umutkeltek/healthsave-observatory.git
cd healthsave-observatory
./healthsave setup basic
./healthsave doctor
./healthsave tui
```

`./healthsave` is the same pattern as `./setup.sh`, `./configure`, `./gradlew`,
or `./mvnw`: a product-owned launcher that works before a global command exists.

## Local Global Wrapper

Works after a checkout exists:

```bash
./healthsave install-cli
healthsave doctor
```

This installs a small wrapper into `~/.local/bin` that calls the checkout's
`./healthsave`. It avoids sudo, Homebrew, and npm global installs.

## Homebrew

Homebrew is the macOS/Linux package-manager release path after the first GitHub
release artifact exists. It should install the same bootstrapper or a
single-file wrapper, not a second setup implementation.

Target flow:

```bash
brew tap healthsave/observatory
brew install healthsave
healthsave setup basic ~/healthsave-observatory
healthsave doctor
healthsave tui
```

Required before enabling the tap:

- GitHub release tag and tarball checksum.
- Formula installs `healthsave` and `healthsave-observatory`.
- `brew test healthsave` runs `healthsave --version` and a dry/read-only command.
- Upgrade behavior preserves existing stack directories.

Formula template lives in `packaging/homebrew/healthsave.rb.template`.

## Platform Notes

- macOS: npm/npx, repo-local launcher, local wrapper, and Homebrew are viable.
- Linux: npm/npx, repo-local launcher, and local wrapper are primary. Homebrew on
  Linux is optional.
- Windows: supported path is WSL2 with Docker Desktop WSL integration. Run npm,
  npx, and `healthsave` inside WSL2, not native PowerShell.

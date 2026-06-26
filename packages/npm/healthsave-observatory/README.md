# healthsave

Bootstrap and control the self-hosted HealthSave Observatory Docker Compose stack.

## Install

```bash
npm i -g healthsave
healthsave onboard
```

No global install:

```bash
npx healthsave
```

Both commands create or reuse `~/healthsave-observatory` and open the guided installer/control center. The npm package owns the public `healthsave` command; checkout-local wrapper install is explicit for manual checkouts.

## Commands

```bash
healthsave onboard [dir]
healthsave version
healthsave init [dir]
healthsave setup [basic|advanced] [dir]
healthsave doctor [dir] --json
healthsave status [dir] --json
healthsave layers [dir] --json
healthsave logs [dir] [layer]
healthsave up [dir]
healthsave down [dir]
healthsave verify [dir]
healthsave install-cli [dir]
healthsave uninstall-cli [dir]
```

Use `healthsave onboard` for humans. Use named commands for scripts and agents. This package also exposes `healthsave-observatory` as a longer alias.

Uninstall the npm bootstrapper:

```bash
npm uninstall -g healthsave
```

Remove only the checkout-local wrapper:

```bash
healthsave uninstall-cli
```

Neither uninstall command removes the checkout directory, containers, volumes, config, or health data.

## Platform

- macOS: Docker Desktop.
- Linux: Docker Engine or Docker Desktop.
- WSL2: Docker Desktop WSL integration enabled.
- Native Windows: use WSL2 today.
- Termux: not supported because Docker Compose is required.

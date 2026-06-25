# healthsave

Bootstrap and control the self-hosted HealthSave Observatory stack from npm.

## Quick Start

```bash
npx healthsave setup basic ~/healthsave-observatory
healthsave doctor
healthsave tui
```

`npx healthsave` creates or finds a HealthSave Observatory checkout, installs
the local `healthsave` wrapper when possible, then delegates to that checkout's
real CLI. Docker Compose setup logic stays in the repository; this npm package
is only the bootstrapper.

## Commands

```bash
healthsave tui [dir]
healthsave init [dir]
healthsave setup [basic|advanced] [dir]
healthsave doctor [dir] --json
healthsave status [dir]
healthsave layers [dir]
healthsave logs [dir] [layer]
healthsave up [dir]
healthsave down [dir]
healthsave verify [dir]
```

Use `healthsave tui` for the human control center. It supports arrow keys and
Enter for setup, stack control, optional layer toggles, doctor/status, logs,
verification, and CLI installation.

Use named subcommands for automation and agents.

This package also exposes `healthsave-observatory` as a longer alias.

## Platform

- macOS: Docker Desktop and Terminal.
- Linux: Docker Engine or Docker Desktop.
- Windows: WSL2 with Docker Desktop WSL integration enabled. Run commands
  inside WSL2, not native PowerShell.

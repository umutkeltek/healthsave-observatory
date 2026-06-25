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

Both commands create or reuse `~/healthsave-observatory`, install the local wrapper when possible, and open the guided installer/control center.

## Commands

```bash
healthsave onboard [dir]
healthsave init [dir]
healthsave setup [basic|advanced] [dir]
healthsave doctor [dir] --json
healthsave status [dir] --json
healthsave layers [dir] --json
healthsave logs [dir] [layer]
healthsave up [dir]
healthsave down [dir]
healthsave verify [dir]
```

Use `healthsave onboard` for humans. Use named commands for scripts and agents.

This package also exposes `healthsave-observatory` as a longer alias.

## Platform

- macOS: Docker Desktop.
- Linux: Docker Engine or Docker Desktop.
- WSL2: Docker Desktop WSL integration enabled.
- Native Windows: use WSL2 today.
- Termux: not supported because Docker Compose is required.

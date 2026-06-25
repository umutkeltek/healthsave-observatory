# Homebrew Packaging

This directory holds the Homebrew release template for HealthSave Observatory.

Do not publish a tap from this template until a GitHub release tarball exists and
the SHA256 is filled in. The public macOS/Linux Homebrew path should install the
same `healthsave` bootstrapper used by npm/npx and must not duplicate setup
logic.

Target flow after tap publication:

```bash
brew tap healthsave/observatory
brew install healthsave
healthsave setup basic ~/healthsave-observatory
healthsave doctor ~/healthsave-observatory
```

Before publishing, verify:

```bash
brew audit --strict --online healthsave
brew test healthsave
```

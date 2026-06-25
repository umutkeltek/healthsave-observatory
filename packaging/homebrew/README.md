# Homebrew Packaging

This directory holds the Homebrew formula template for HealthSave Observatory. Do not publish a tap from the template until a GitHub release tarball exists and the SHA256 is filled in.

The macOS/Linux Homebrew path should install the same `healthsave` bootstrapper used by npm/npx. It must not duplicate setup logic.

Target flow after tap publication:

```bash
brew tap healthsave/observatory
brew install healthsave
healthsave onboard
```

Before publishing, verify:

```bash
brew audit --strict --online healthsave
brew test healthsave
```

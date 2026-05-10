# integrations/

Third-party-system integration examples. These are *examples*, not
core product surfaces. They show how to plug `health-data-hub` into
an existing self-hosted stack.

| path | what it integrates | populated |
|------|--------------------|-----------|
| `home-assistant/` | Example HA SQL sensors + automations against the Timescale data plane | Phase 1A |

Rule: integrations import from the API or read from the storage
ports — never from internal `apps/` or `packages/` modules. They are
demonstrations of the public contract, not consumers of internal
state.

# SPDX-License-Identifier: Apache-2.0
"""Plugin SDK error hierarchy.

Every error the SDK raises subclasses :class:`PluginError`. Callers
that want to fail-loud on any plugin issue can catch the base; callers
that want to differentiate (e.g., "skip incompatible, fail malformed")
catch the specific subclass.

All errors carry the offending ``plugin_id`` (or path, when the
manifest itself is malformed and no id is available) so log output
is grep-able.
"""

from __future__ import annotations


class PluginError(Exception):
    """Base for every Plugin SDK error."""


class PluginManifestError(PluginError):
    """The plugin.yaml file failed to parse or failed schema validation.

    Raised by :func:`plugin_sdk.discovery.load_manifest`. The original
    parse / validation exception is chained via ``__cause__``.
    """

    def __init__(self, *, plugin_dir: str, message: str) -> None:
        super().__init__(f"{plugin_dir}: {message}")
        self.plugin_dir = plugin_dir


class PluginSdkVersionMismatch(PluginError):
    """Plugin's declared ``sdk_version`` range excludes the running SDK.

    The plugin is well-formed but targets a different SDK version. The
    loader skips it and surfaces this so operators can decide whether
    to upgrade the SDK or downgrade the plugin.
    """

    def __init__(self, *, plugin_id: str, declared: str, running: str) -> None:
        super().__init__(
            f"plugin {plugin_id!r} targets SDK {declared!r}; running SDK is {running!r}"
        )
        self.plugin_id = plugin_id
        self.declared = declared
        self.running = running


class PluginNotFoundError(PluginError):
    """Discovery walk could not locate a plugin by ``id`` + ``kind``."""

    def __init__(self, *, kind: str, plugin_id: str) -> None:
        super().__init__(f"no {kind} plugin with id={plugin_id!r}")
        self.kind = kind
        self.plugin_id = plugin_id


class PluginEntrypointError(PluginError):
    """The plugin's declared ``entrypoint`` could not be resolved.

    Typically: module import failed, attribute missing, or attribute
    is not a subclass of the expected base.
    """

    def __init__(self, *, plugin_id: str, entrypoint: str, message: str) -> None:
        super().__init__(f"plugin {plugin_id!r} entrypoint {entrypoint!r}: {message}")
        self.plugin_id = plugin_id
        self.entrypoint = entrypoint

// bun test preload (see bunfig.toml). Next's server runtime puts
// AsyncLocalStorage on globalThis before any request API loads; without it
// cookies()/headers() can never see a request store in tests. Outside a
// request scope they still throw exactly as before.
import { AsyncLocalStorage } from "node:async_hooks";

(globalThis as { AsyncLocalStorage?: unknown }).AsyncLocalStorage = AsyncLocalStorage;

// "server-only" is a build-time marker Next resolves; bun cannot. An empty
// stand-in lets tests import server modules (the root layout) the way Next does.
// require, not import: this file is typechecked with the app, which has no
// bun:test types.
const { mock } = require("bun:test") as { mock: { module(name: string, factory: () => object): void } };
mock.module("server-only", () => ({}));

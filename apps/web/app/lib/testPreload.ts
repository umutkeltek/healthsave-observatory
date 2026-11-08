// bun test preload (see bunfig.toml). Next's server runtime puts
// AsyncLocalStorage on globalThis before any request API loads; without it
// cookies()/headers() can never see a request store in tests. Outside a
// request scope they still throw exactly as before.
import { AsyncLocalStorage } from "node:async_hooks";

(globalThis as { AsyncLocalStorage?: unknown }).AsyncLocalStorage = AsyncLocalStorage;

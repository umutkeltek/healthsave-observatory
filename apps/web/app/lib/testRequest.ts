// Test helper: run code the way Next runs a request, so cookies() returns the
// given cookies. Needs the preload in bunfig.toml. Imported by tests only.
import { workAsyncStorage } from "next/dist/server/app-render/work-async-storage.external";
import { workUnitAsyncStorage } from "next/dist/server/app-render/work-unit-async-storage.external";
import { RequestCookies } from "next/dist/server/web/spec-extension/cookies";

export function inRequest<T>(cookie: string, fn: () => Promise<T>): Promise<T> {
  const unit = { type: "request", phase: "render", cookies: new RequestCookies(new Headers({ cookie })) };
  return workAsyncStorage.run({ route: "/test" } as never, () => workUnitAsyncStorage.run(unit as never, fn));
}

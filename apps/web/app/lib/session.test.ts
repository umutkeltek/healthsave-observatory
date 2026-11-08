import { describe, expect, test } from "bun:test";

import {
  isSignInRequired,
  pollState,
  runAction,
  SIGN_IN_REQUIRED,
  SIGNED_OUT_MESSAGE,
  signInPath,
} from "./session";

describe("expired session", () => {
  test("the live poll treats 401 as signed out, not offline", () => {
    expect(pollState(401, true)).toBe("signed-out");
    expect(pollState(401, false)).toBe("signed-out");
    expect(pollState(502, true)).toBe("offline");
    expect(pollState(null, false)).toBe("unknown");
    expect(pollState(304, false)).toBe("live");
  });

  test("an action rejected for sign-in becomes a failed result, so the form keeps its input", async () => {
    const result = await runAction(async (): Promise<{ ok: boolean; error?: string }> => {
      throw new Error(SIGN_IN_REQUIRED);
    });
    expect(result).toEqual({ ok: false, error: SIGNED_OUT_MESSAGE });
  });

  test("any other rejection still reaches the error boundary", async () => {
    await expect(
      runAction(async (): Promise<{ ok: boolean }> => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
  });

  test("results pass through untouched", async () => {
    expect(await runAction(async () => ({ ok: true }))).toEqual({ ok: true });
  });

  test("recognises only the proxy's sign-in answer", () => {
    expect(isSignInRequired(new Error(SIGN_IN_REQUIRED))).toBe(true);
    expect(isSignInRequired(new Error("An unexpected response was received from the server."))).toBe(false);
    expect(isSignInRequired("sign_in_required")).toBe(false);
  });

  test("sign-in returns to the page the person was on", () => {
    expect(signInPath("/timeline?x=1")).toBe("/login?next=%2Ftimeline%3Fx%3D1");
    expect(signInPath("/")).toBe("/login");
  });
});

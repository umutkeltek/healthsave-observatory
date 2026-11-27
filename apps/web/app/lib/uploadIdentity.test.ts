import { expect, test } from "bun:test";
import { newUploadId } from "./uploadIdentity";

test("upload identities remain UUIDs on LAN HTTP without randomUUID", () => {
  const descriptor = Object.getOwnPropertyDescriptor(crypto, "randomUUID");
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    const first = newUploadId();
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newUploadId()).not.toBe(first);
  } finally {
    if (descriptor) Object.defineProperty(crypto, "randomUUID", descriptor);
    else delete (crypto as unknown as Record<string, unknown>).randomUUID;
  }
});

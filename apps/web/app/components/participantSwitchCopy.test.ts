// The participant switcher is translated: what it shows after a failed switch
// must be in the same language as the rest of it.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { setParticipantAction } from "../lib/actions";
import { dictionaries, LOCALE_COOKIE } from "../lib/i18n";
import { DEFAULT_OWNER_ID } from "../lib/participants";
import { inRequest } from "../lib/testRequest";
import { clearSwrCache } from "../lib/ttlCache";
import { resetWebAuthStoreForTests } from "../lib/webAuthStore.server";
import { switchParticipant } from "./ParticipantSelect";

const ALICE = "7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00";
const saved = {
  password: process.env.WEB_PASSWORD,
  file: process.env.WEB_AUTH_FILE,
  preview: process.env.HEALTHSAVE_EXPERIMENTAL_LOCALES,
};
const realFetch = globalThis.fetch;
let dir = "";

beforeEach(() => {
  clearSwrCache();
  dir = mkdtempSync(join(tmpdir(), "hs-switch-"));
  process.env.WEB_AUTH_FILE = join(dir, "web-auth.json");
  process.env.HEALTHSAVE_EXPERIMENTAL_LOCALES = "1";
  delete process.env.WEB_PASSWORD;
  globalThis.fetch = (async () =>
    Response.json({
      count: 1,
      owners: [{ id: DEFAULT_OWNER_ID, label: null, is_default: true, active: true, scopes: [], created_at: null, last_ingest_at: null }],
    })) as unknown as typeof fetch;
});

afterEach(async () => {
  globalThis.fetch = realFetch;
  clearSwrCache();
  await resetWebAuthStoreForTests();
  rmSync(dir, { recursive: true, force: true });
  for (const [key, value] of [
    ["WEB_PASSWORD", saved.password],
    ["WEB_AUTH_FILE", saved.file],
    ["HEALTHSAVE_EXPERIMENTAL_LOCALES", saved.preview],
  ] as const) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

describe("participant switch messages follow the interface language", () => {
  // The review: "That person is not on this Observatory." was English inside a
  // switcher translated into six locales.
  test("an unlisted person is refused in the chosen language", async () => {
    const result = await inRequest(`${LOCALE_COOKIE}=es`, () => setParticipantAction(ALICE));
    expect(result).toEqual({ ok: false, error: dictionaries.es.participants.notListed });
  });

  test("an ended session is reported in the switcher's language", async () => {
    process.env.WEB_PASSWORD = "correct horse battery";
    const result = await inRequest("", () => switchParticipant(ALICE, dictionaries.ja));
    expect(result).toEqual({ ok: false, error: dictionaries.ja.session.signedOut });
  });
});

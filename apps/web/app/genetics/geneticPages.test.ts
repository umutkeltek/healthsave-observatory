import { afterEach, beforeEach, expect, test } from "bun:test";
import { inRequest } from "../lib/testRequest";
import { clearSwrCache } from "../lib/ttlCache";
import { DEFAULT_OWNER_ID, PARTICIPANT_COOKIE } from "../lib/participants";
import { GeneticHome } from "../components/Genetics";
import { GeneticDocumentView } from "../components/Genetics";
import ImportPage from "./page";
import ReportPage from "./[id]/page";

const realFetch = globalThis.fetch;
const PARTICIPANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const params = Promise.resolve({ id: "11111111-1111-4111-8111-111111111111" });

beforeEach(() => {
  clearSwrCache();
  globalThis.fetch = (async () => Response.json({ owners: [
    { id: DEFAULT_OWNER_ID, is_default: true },
    { id: PARTICIPANT, is_default: false },
  ], count: 2 })) as typeof fetch;
});
afterEach(() => { globalThis.fetch = realFetch; clearSwrCache(); });

test("switching person removes all primary genetic client components", async () => {
  for (const page of [ImportPage, () => ReportPage({ params })]) {
    const rendered = await inRequest(`${PARTICIPANT_COOKIE}=${PARTICIPANT}`, page);
    expect(rendered.type).toBe("p");
    expect(rendered.props.children).toContain("Switch to the primary person");
  }
});

test("primary person can open upload and report screens", async () => {
  expect((await inRequest("", ImportPage)).type).toBe(GeneticHome);
  expect((await inRequest("", () => ReportPage({ params }))).type).toBe(GeneticDocumentView);
});

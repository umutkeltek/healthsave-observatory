import { afterEach, beforeEach, expect, test } from "bun:test";
import { inRequest } from "../../lib/testRequest";
import { clearSwrCache } from "../../lib/ttlCache";
import { DEFAULT_OWNER_ID, PARTICIPANT_COOKIE } from "../../lib/participants";
import { LabImport } from "../../components/LabImport";
import { LabReport } from "../../components/LabReport";
import ImportPage from "./page";
import ReviewPage from "./[id]/page";
import ReportPage from "./[id]/report/page";

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

test("switching person removes all primary lab document client components", async () => {
  for (const page of [ImportPage, () => ReviewPage({ params }), () => ReportPage({ params })]) {
    const rendered = await inRequest(`${PARTICIPANT_COOKIE}=${PARTICIPANT}`, page);
    expect(rendered.type).toBe("p");
    expect(rendered.props.children).toContain("Switch to the primary person");
  }
});

test("primary person can open upload, review and report screens", async () => {
  expect((await inRequest("", ImportPage)).type).toBe(LabImport);
  const review = await inRequest("", () => ReviewPage({ params }));
  expect(review.type).toBe(LabImport);
  expect(review.props.documentId).toBe((await params).id);
  expect((await inRequest("", () => ReportPage({ params }))).type).toBe(LabReport);
});

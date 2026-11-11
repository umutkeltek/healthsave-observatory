import { participantView } from "../../../lib/api";
import { isSameOriginPost } from "../../../lib/webAuth";

export const dynamic = "force-dynamic";
const API_BASE = process.env.API_BASE ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";
const LIMIT = 50 * 1024 * 1024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PRIVATE = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
type Context = { params: Promise<{ path?: string[] }> };

async function bodyBytes(request: Request, limit: number) {
  const reader = request.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks: Uint8Array[] = []; let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > limit) { await reader.cancel(); throw new RangeError("The request exceeds its size limit."); }
    chunks.push(value);
  }
  const result = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}

async function forward(request: Request, context: Context) {
  const { path = [] } = await context.params;
  const method = request.method;
  const mutation = method !== "GET";
  const document = UUID.test(path[0] ?? "");
  const valid = method === "GET" ? (path.length === 0 ||
    (path.length === 1 && (path[0] === "reference" || document)) ||
    (document && path.length === 2 && path[1] === "original") ||
    (document && path.length === 3 && path[1] === "reports" && UUID.test(path[2]))) :
    method === "POST" ? (path.length === 0 || (path.length === 1 && path[0] === "reference") ||
      (document && path.length === 2 && path[1] === "reanalyze")) :
    method === "DELETE" && document && (path.length === 1 || (path.length === 2 && path[1] === "original"));
  if (!valid) return Response.json({ detail: "Unknown genetic-record action." }, { status: 404, headers: PRIVATE });
  if (mutation && (!(request.headers.get("origin") || request.headers.get("sec-fetch-site")) || !isSameOriginPost(request.headers))) {
    return Response.json({ detail: "Open this form on your Observatory before continuing." }, { status: 403, headers: PRIVATE });
  }
  if ((await participantView()).person.kind !== "primary") {
    return Response.json({ detail: "Switch to the primary person to view genetic records." }, { status: 403, headers: PRIVATE });
  }
  try {
    const upload = method === "POST" && path.length === 0;
    const headers: Record<string, string> = {};
    if (API_KEY) headers["X-API-Key"] = API_KEY;
    if (mutation) headers["Content-Type"] = upload ? "application/octet-stream" : "application/json";
    if (upload) for (const name of ["x-file-name", "x-genome-assembly", "x-genetic-consent", "x-forward-strand", "x-retain-original"]) {
      headers[name] = request.headers.get(name) ?? "";
    }
    const bytes = mutation ? await bodyBytes(request, upload ? LIMIT : 4096) : undefined;
    const response = await fetch(`${API_BASE}/api/v2/genetics${path.length ? "/" + path.join("/") : ""}`, {
      method, headers, body: bytes as BodyInit | undefined, cache: "no-store", signal: AbortSignal.timeout(120_000),
    });
    const output = new Headers(PRIVATE);
    output.set("Content-Type", response.headers.get("content-type") ?? "application/json");
    if (path[1] === "original") {
      output.set("Content-Security-Policy", "sandbox; default-src 'none'");
      const disposition = response.headers.get("content-disposition");
      if (disposition) output.set("Content-Disposition", disposition);
    }
    return new Response(response.body, { status: response.status, headers: output });
  } catch (error) {
    return Response.json({ detail: error instanceof RangeError ? error.message : "The Observatory could not finish this request. Check your records before retrying an upload." },
      { status: error instanceof RangeError ? 413 : 502, headers: PRIVATE });
  }
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;

import { participantView } from "../../../lib/api";
import { invalidateSwr } from "../../../lib/ttlCache";
import { isSameOriginPost } from "../../../lib/webAuth";

export const dynamic = "force-dynamic";
const API_BASE = process.env.API_BASE ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";
const LIMIT = 5 * 1024 * 1024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
type Context = { params: Promise<{ path?: string[] }> };
const PRIVATE = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };

async function boundedBody(request: Request): Promise<Uint8Array> {
  const reader = request.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > LIMIT) {
      await reader.cancel();
      throw new RangeError("Choose a file no larger than 5 MB.");
    }
    chunks.push(value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; }
  return body;
}

async function forward(request: Request, context: Context): Promise<Response> {
  const { path = [] } = await context.params;
  const isPost = request.method === "POST";
  const isDelete = request.method === "DELETE";
  const mutation = isPost || isDelete;
  const valid = isDelete ? (path.length === 1 && UUID.test(path[0])) :
    path.length === 0 || (!isPost && path.length === 1 && path[0] === "catalog") ||
    (UUID.test(path[0] ?? "") && ((!isPost && path.length === 1) ||
      (path.length === 2 && (isPost ? path[1] === "commit" : ["report", "original", "deletion"].includes(path[1])))));
  if (!valid) return Response.json({ detail: "Unknown lab import action." }, { status: 404, headers: PRIVATE });
  if (mutation && (!(request.headers.get("origin") || request.headers.get("sec-fetch-site")) ||
    !isSameOriginPost(request.headers))) {
    return Response.json({ detail: "Open this form on your Observatory before saving." }, { status: 403, headers: PRIVATE });
  }
  if ((await participantView()).person.kind !== "primary") {
    return Response.json({ detail: "Switch to the primary person to import or view lab documents." }, { status: 403, headers: PRIVATE });
  }
  try {
    const headers: Record<string, string> = {};
    if (API_KEY) headers["X-API-Key"] = API_KEY;
    if (mutation) {
      headers["Content-Type"] = path.length ? "application/json" : "application/octet-stream";
      headers["X-File-Name"] = request.headers.get("x-file-name") ?? "";
      const uploadId = request.headers.get("x-upload-id");
      if (!path.length && uploadId !== null) headers["X-Upload-ID"] = uploadId;
    }
    const body = mutation ? await boundedBody(request) : undefined;
    const cursor = !mutation && path.length === 0 ? new URL(request.url).searchParams.get("cursor") : null;
    const query = cursor ? `?${new URLSearchParams({ cursor })}` : "";
    const response = await fetch(`${API_BASE}/api/v2/lab-imports${path.length ? "/" + path.join("/") : ""}${query}`, {
      method: request.method, headers, body: body as BodyInit | undefined,
      cache: "no-store", signal: AbortSignal.timeout(120_000),
    });
    if (response.ok && (isDelete || (isPost && path[1] === "commit"))) invalidateSwr(["labs", "lab"]);
    const out = new Headers(PRIVATE);
    out.set("Content-Type", response.headers.get("content-type") ?? "application/json");
    const disposition = response.headers.get("content-disposition");
    if (disposition) out.set("Content-Disposition", disposition);
    if (path[1] === "original") out.set("Content-Security-Policy", "sandbox; default-src 'none'");
    return new Response(response.body, { status: response.status, headers: out });
  } catch (error) {
    if (error instanceof RangeError) return Response.json({ detail: error.message }, { status: 413, headers: PRIVATE });
    return Response.json({ detail: "The Observatory could not finish this request. Your draft can be retried." }, { status: 502, headers: PRIVATE });
  }
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;

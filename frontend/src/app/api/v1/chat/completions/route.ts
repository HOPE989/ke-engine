const chatApiBaseUrl = process.env.CHAT_API_BASE_URL ?? "http://localhost:8001";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  const upstreamHeaders = new Headers();
  upstreamHeaders.set(
    "Content-Type",
    request.headers.get("Content-Type") ?? "application/json"
  );
  const mockUserId = request.headers.get("X-Mock-User-Id");
  if (mockUserId) {
    upstreamHeaders.set("X-Mock-User-Id", mockUserId);
  }

  const upstream = await fetch(`${chatApiBaseUrl}/api/v1/chat/completions`, {
    method: "POST",
    headers: upstreamHeaders,
    body: await request.arrayBuffer(),
    cache: "no-store"
  });

  const responseHeaders = new Headers();
  responseHeaders.set(
    "Content-Type",
    upstream.headers.get("Content-Type") ?? "text/event-stream"
  );
  responseHeaders.set("Cache-Control", "no-cache, no-transform");
  responseHeaders.set("X-Accel-Buffering", "no");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders
  });
}

import assert from "node:assert/strict";
import test from "node:test";

import { POST } from "./route.ts";

test("completion 代理在上游结束前转发首个 SSE 分片", async () => {
  const originalFetch = globalThis.fetch;
  let releaseSecondChunk!: () => void;
  const secondChunkReady = new Promise<void>((resolve) => {
    releaseSecondChunk = resolve;
  });

  globalThis.fetch = async () => {
    const encoder = new TextEncoder();
    return new Response(
      new ReadableStream({
        async start(controller) {
          controller.enqueue(encoder.encode("event: metadata\ndata: {}\n\n"));
          await secondChunkReady;
          controller.enqueue(encoder.encode("event: completed\ndata: {}\n\n"));
          controller.close();
        }
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } }
    );
  };

  try {
    const response = await POST(
      new Request("http://localhost/api/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Mock-User-Id": "tester"
        },
        body: '{"content":"hello"}'
      })
    );
    const reader = response.body!.getReader();
    const first = await reader.read();

    assert.equal(new TextDecoder().decode(first.value), "event: metadata\ndata: {}\n\n");
    assert.equal(first.done, false);
    releaseSecondChunk();
    await reader.cancel();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

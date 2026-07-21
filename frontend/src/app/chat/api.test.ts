import assert from "node:assert/strict";
import test from "node:test";

import { readJson, streamCompletion } from "./api.ts";

function sseResponse(...chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      }
    }),
    { headers: { "Content-Type": "text/event-stream" } }
  );
}

async function withSseResponse<T>(response: Response, action: () => Promise<T>) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => response) as typeof fetch;
  try {
    return await action();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function completion(response: Response) {
  return withSseResponse(response, () =>
    streamCompletion({
      userId: "tester",
      conversationId: "42",
      content: "继续回答",
      onMetadata: () => {},
      onDelta: () => {}
    })
  );
}

test("非 JSON 错误响应回退到 HTTP 状态提示", async () => {
  const response = new Response("Internal Server Error", { status: 502 });

  await assert.rejects(() => readJson(response), /请求失败，HTTP 502/);
});

test("completed stop 是成功终态", async () => {
  const result = await completion(
    sseResponse('event: completed\ndata: {"assistant_message_id":"3001","finish_reason":"stop"}\n\n')
  );

  assert.equal(result, "stop");
});

test("completed interrupt 是成功终态", async () => {
  const result = await completion(
    sseResponse('event: completed\ndata: {"assistant_message_id":"3002","finish_reason":"interrupt"}\n\n')
  );

  assert.equal(result, "interrupt");
});

test("保留 metadata 和 content_delta 的流处理", async () => {
  const metadata: string[] = [];
  const deltas: string[] = [];
  const response = sseResponse(
    'event: metadata\ndata: {"conversation_id":"42"}\n\nevent: content_delta\ndata: {"content":"你好"}\n\n',
    'event: completed\ndata: {"assistant_message_id":"3001","finish_reason":"stop"}\n\n'
  );

  const result = await withSseResponse(response, () =>
    streamCompletion({
      userId: "tester",
      conversationId: "42",
      content: "继续回答",
      onMetadata: (conversationId) => metadata.push(conversationId),
      onDelta: (content) => deltas.push(content)
    })
  );

  assert.equal(result, "stop");
  assert.deepEqual(metadata, ["42"]);
  assert.deepEqual(deltas, ["你好"]);
});

test("未知 completed finish reason 被拒绝", async () => {
  await assert.rejects(
    () =>
      completion(
        sseResponse('event: completed\ndata: {"assistant_message_id":"3003","finish_reason":"length"}\n\n')
      ),
    /finish reason/
  );
});

test("content_delta 后未收到 completed 即 EOF 被拒绝", async () => {
  await assert.rejects(
    () => completion(sseResponse('event: content_delta\ndata: {"content":"未完成"}\n\n')),
    /completed/
  );
});

test("error 事件被拒绝", async () => {
  await assert.rejects(
    () => completion(sseResponse('event: error\ndata: {"message":"模型生成失败"}\n\n')),
    /模型生成失败/
  );
});

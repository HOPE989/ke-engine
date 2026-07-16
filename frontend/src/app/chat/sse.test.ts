import assert from "node:assert/strict";
import test from "node:test";

import { parseSseFrames } from "./sse.ts";

test("保留未完成分片并解析后续完整事件", () => {
  const first = parseSseFrames('event: metadata\ndata: {"conversation_id":"42"');

  assert.deepEqual(first.events, []);
  assert.equal(first.remainder, 'event: metadata\ndata: {"conversation_id":"42"');

  const second = parseSseFrames(`${first.remainder}}\n\nevent: content_delta\ndata: {"content":"你"}\n\n`);

  assert.deepEqual(second.events, [
    { event: "metadata", data: { conversation_id: "42" } },
    { event: "content_delta", data: { content: "你" } }
  ]);
  assert.equal(second.remainder, "");
});

test("兼容 CRLF，并忽略注释行", () => {
  const result = parseSseFrames(': ping\r\nevent: completed\r\ndata: {"finish_reason":"stop"}\r\n\r\n');

  assert.deepEqual(result.events, [
    { event: "completed", data: { finish_reason: "stop" } }
  ]);
});

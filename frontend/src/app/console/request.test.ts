import assert from "node:assert/strict";
import test from "node:test";

import { buildCurl, buildRequest, type RequestDraft } from "./request.ts";

const base: RequestDraft = {
  method: "POST",
  path: "/api/v1/chat/completions",
  userId: "tester",
  headersText: "{}",
  bodyText: '{"content":"hello"}'
};

test("buildRequest 注入模拟身份与 JSON content type", () => {
  const request = buildRequest(base);
  assert.equal(request.path, base.path);
  assert.deepEqual(request.init.headers, {
    "X-Mock-User-Id": "tester",
    "Content-Type": "application/json"
  });
  assert.equal(request.init.body, '{"content":"hello"}');
});

test("buildRequest 拒绝远程和协议相对地址", () => {
  assert.throws(() => buildRequest({ ...base, path: "https://example.com" }), /同源路径/);
  assert.throws(() => buildRequest({ ...base, path: "//example.com" }), /同源路径/);
});

test("buildCurl 生成可复现命令", () => {
  const curl = buildCurl(base, "http://localhost:3000");
  assert.match(curl, /curl -i -X POST/);
  assert.match(curl, /x-mock-user-id: tester/);
  assert.match(curl, /--data-raw/);
});

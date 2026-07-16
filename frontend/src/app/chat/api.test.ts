import assert from "node:assert/strict";
import test from "node:test";

import { readJson } from "./api.ts";

test("非 JSON 错误响应回退到 HTTP 状态提示", async () => {
  const response = new Response("Internal Server Error", { status: 502 });

  await assert.rejects(() => readJson(response), /请求失败，HTTP 502/);
});

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export type RequestDraft = {
  method: HttpMethod;
  path: string;
  userId: string;
  headersText: string;
  bodyText: string;
};

function parseObject(text: string, label: string): Record<string, string> {
  if (!text.trim()) return {};

  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`${label}不是合法 JSON。`);
  }
  if (!value || Array.isArray(value) || typeof value !== "object") {
    throw new Error(`${label}必须是 JSON 对象。`);
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, String(item)])
  );
}

export function buildRequest(draft: RequestDraft) {
  const path = draft.path.trim();
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("请求路径必须是以单个 / 开头的同源路径。");
  }

  const headers = parseObject(draft.headersText, "附加请求头");
  if (draft.userId.trim()) {
    headers["X-Mock-User-Id"] = draft.userId.trim();
  }

  let body: string | undefined;
  if (!["GET", "DELETE"].includes(draft.method) && draft.bodyText.trim()) {
    try {
      body = JSON.stringify(JSON.parse(draft.bodyText));
    } catch {
      throw new Error("请求体不是合法 JSON。");
    }
    if (!Object.keys(headers).some((key) => key.toLowerCase() === "content-type")) {
      headers["Content-Type"] = "application/json";
    }
  }

  return { path, init: { method: draft.method, headers, body } satisfies RequestInit };
}

function shellQuote(value: string) {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

export function buildCurl(draft: RequestDraft, origin: string) {
  const { path, init } = buildRequest(draft);
  const parts = [`curl -i -X ${draft.method}`, shellQuote(`${origin}${path}`)];
  const headers = new Headers(init.headers);
  headers.forEach((value, key) => {
    parts.push(`-H ${shellQuote(`${key}: ${value}`)}`);
  });
  if (init.body) parts.push(`--data-raw ${shellQuote(String(init.body))}`);
  return parts.join(" \\\n  ");
}

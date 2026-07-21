import { parseSseFrames } from "./sse.ts";
import type {
  ApiResponse,
  CompletionFinishReason,
  ConversationPage,
  MessagePage
} from "./types";

const chatEndpoint = "/api/v1/chat";

function headers(userId: string) {
  return { "X-Mock-User-Id": userId };
}

function isFinishReason(value: unknown): value is CompletionFinishReason {
  return value === "stop" || value === "interrupt";
}

export async function readJson<T>(response: Response): Promise<ApiResponse<T>> {
  let payload: ApiResponse<T>;
  try {
    payload = (await response.json()) as ApiResponse<T>;
  } catch {
    throw new Error(`请求失败，HTTP ${response.status}`);
  }
  if (!response.ok || payload.data === null) {
    throw new Error(payload.message || `请求失败，HTTP ${response.status}`);
  }
  return payload;
}

export async function listConversations(userId: string) {
  const response = await fetch(`${chatEndpoint}/conversations?limit=100`, {
    headers: headers(userId),
    cache: "no-store"
  });
  return (await readJson<ConversationPage>(response)).data!;
}

export async function listMessages(userId: string, conversationId: string) {
  const response = await fetch(
    `${chatEndpoint}/conversations/${conversationId}/messages?limit=100`,
    { headers: headers(userId), cache: "no-store" }
  );
  return (await readJson<MessagePage>(response)).data!;
}

export async function streamCompletion(options: {
  userId: string;
  conversationId: string | null;
  content: string;
  onMetadata: (conversationId: string) => void;
  onDelta: (content: string) => void;
}): Promise<CompletionFinishReason> {
  const response = await fetch(`${chatEndpoint}/completions`, {
    method: "POST",
    headers: {
      ...headers(options.userId),
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      ...(options.conversationId
        ? { conversation_id: options.conversationId }
        : {}),
      content: options.content
    })
  });

  if (!response.ok) {
    let message = `请求失败，HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as ApiResponse<never>;
      message = payload.message || message;
    } catch {
      // 保留 HTTP 状态作为兜底错误。
    }
    throw new Error(message);
  }
  if (!response.body) {
    throw new Error("浏览器没有收到可读取的 SSE 响应流。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const parsed = parseSseFrames(buffer);
      buffer = parsed.remainder;

      for (const item of parsed.events) {
        if (item.event === "metadata") {
          options.onMetadata(String(item.data.conversation_id));
        } else if (item.event === "content_delta") {
          options.onDelta(String(item.data.content ?? ""));
        } else if (item.event === "completed") {
          if (!isFinishReason(item.data.finish_reason)) {
            throw new Error("completed 事件包含未知的 finish reason。");
          }
          try {
            await reader.cancel();
          } catch {
            // completed 已经是成功终态，取消失败不应覆盖该结果。
          }
          return item.data.finish_reason;
        } else if (item.event === "error") {
          throw new Error(String(item.data.message ?? "模型生成失败"));
        }
      }

      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }

  throw new Error("SSE 响应在收到 completed 事件前结束。");
}

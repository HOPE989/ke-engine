"use client";

import { FormEvent, useMemo, useState } from "react";

import { TestNav } from "../components/TestNav";
import { buildCurl, buildRequest, type HttpMethod, type RequestDraft } from "./request";
import styles from "./console.module.css";

type Preset = RequestDraft & {
  name: string;
  description: string;
};

type Exchange = {
  id: number;
  method: HttpMethod;
  path: string;
  status: number;
  statusText: string;
  duration: number;
  headers: string;
  body: string;
  curl: string;
};

const presets: Preset[] = [
  {
    name: "Document 健康检查",
    description: "确认 8000 端口的文档服务可用",
    method: "GET",
    path: "/api/health/document",
    userId: "",
    headersText: "{}",
    bodyText: ""
  },
  {
    name: "Chat 健康检查",
    description: "确认 8001 端口的 Chat 服务可用",
    method: "GET",
    path: "/api/health/chat",
    userId: "",
    headersText: "{}",
    bodyText: ""
  },
  {
    name: "会话列表",
    description: "按模拟用户读取最近 20 个会话",
    method: "GET",
    path: "/api/v1/chat/conversations?limit=20",
    userId: "local-tester",
    headersText: "{}",
    bodyText: ""
  },
  {
    name: "消息历史",
    description: "将 42 替换为真实 conversation_id",
    method: "GET",
    path: "/api/v1/chat/conversations/42/messages?limit=100",
    userId: "local-tester",
    headersText: "{}",
    bodyText: ""
  },
  {
    name: "文档状态",
    description: "将 42 替换为真实 doc_id",
    method: "GET",
    path: "/api/v1/document/42",
    userId: "",
    headersText: "{}",
    bodyText: ""
  },
  {
    name: "触发文档切分",
    description: "验证状态约束、锁和切分持久化",
    method: "POST",
    path: "/api/v1/document/42/chunk",
    userId: "",
    headersText: "{}",
    bodyText: '{\n  "chunk_size": 1000,\n  "overlap": 100\n}'
  },
  {
    name: "触发向量入库",
    description: "将已切分文档派发到向量入库任务",
    method: "POST",
    path: "/api/v1/document/42/embed-store",
    userId: "",
    headersText: "{}",
    bodyText: ""
  },
  {
    name: "Chat 原始 SSE",
    description: "查看未加工的 metadata、delta 和终态事件",
    method: "POST",
    path: "/api/v1/chat/completions",
    userId: "local-tester",
    headersText: "{}",
    bodyText: '{\n  "content": "请返回一句简短的测试响应"\n}'
  }
];

const initialDraft: RequestDraft = { ...presets[0] };

function prettyBody(value: string) {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

export default function ConsolePage() {
  const [draft, setDraft] = useState<RequestDraft>(initialDraft);
  const [history, setHistory] = useState<Exchange[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const selected = useMemo(
    () => history.find((item) => item.id === selectedId) ?? history[0],
    [history, selectedId]
  );

  function applyPreset(preset: Preset) {
    setDraft({
      method: preset.method,
      path: preset.path,
      userId: preset.userId,
      headersText: preset.headersText,
      bodyText: preset.bodyText
    });
    setError("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setCopied(false);

    let request: ReturnType<typeof buildRequest>;
    try {
      request = buildRequest(draft);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "请求配置无效。");
      return;
    }

    setRunning(true);
    const startedAt = performance.now();
    try {
      const response = await fetch(request.path, {
        ...request.init,
        cache: "no-store"
      });
      const body = await response.text();
      const exchange: Exchange = {
        id: Date.now(),
        method: draft.method,
        path: request.path,
        status: response.status,
        statusText: response.statusText,
        duration: Math.round(performance.now() - startedAt),
        headers: [...response.headers.entries()]
          .map(([key, value]) => `${key}: ${value}`)
          .join("\n"),
        body: prettyBody(body),
        curl: buildCurl(draft, window.location.origin)
      };
      setHistory((current) => [exchange, ...current].slice(0, 20));
      setSelectedId(exchange.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "网络请求失败。");
    } finally {
      setRunning(false);
    }
  }

  async function copyCurl() {
    if (!selected) return;
    await navigator.clipboard.writeText(selected.curl);
    setCopied(true);
  }

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div>
          <span className={styles.kicker}>KE ENGINE / API LAB</span>
          <h1>后端接口实验室</h1>
          <p>发送真实同源请求，保留最近 20 次结果，用原始响应定位接口问题。</p>
        </div>
        <TestNav current="console" />
      </header>

      <section className={styles.presetSection} aria-label="接口预设">
        {presets.map((preset, index) => (
          <button type="button" key={preset.name} onClick={() => applyPreset(preset)}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{preset.name}</strong>
            <small>{preset.description}</small>
          </button>
        ))}
      </section>

      <section className={styles.workspace}>
        <form className={styles.requestPanel} onSubmit={submit}>
          <div className={styles.panelTitle}>
            <div>
              <span>REQUEST</span>
              <h2>构造请求</h2>
            </div>
            <span className={styles.localOnly}>仅允许同源路径</span>
          </div>

          <div className={styles.endpointRow}>
            <select
              aria-label="HTTP 方法"
              value={draft.method}
              onChange={(event) =>
                setDraft({ ...draft, method: event.target.value as HttpMethod })
              }
            >
              {["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => (
                <option key={method}>{method}</option>
              ))}
            </select>
            <input
              aria-label="请求路径"
              value={draft.path}
              onChange={(event) => setDraft({ ...draft, path: event.target.value })}
              spellCheck={false}
            />
          </div>

          <label>
            <span>模拟用户 <small>X-Mock-User-Id</small></span>
            <input
              value={draft.userId}
              onChange={(event) => setDraft({ ...draft, userId: event.target.value })}
              placeholder="公开接口可留空"
            />
          </label>

          <label>
            <span>附加请求头 <small>JSON 对象</small></span>
            <textarea
              value={draft.headersText}
              onChange={(event) =>
                setDraft({ ...draft, headersText: event.target.value })
              }
              rows={4}
              spellCheck={false}
            />
          </label>

          <label>
            <span>请求体 <small>JSON</small></span>
            <textarea
              value={draft.bodyText}
              onChange={(event) => setDraft({ ...draft, bodyText: event.target.value })}
              rows={8}
              spellCheck={false}
              disabled={draft.method === "GET" || draft.method === "DELETE"}
              placeholder="GET / DELETE 请求不发送 body"
            />
          </label>

          {error ? <p className={styles.error}>{error}</p> : null}
          <button className={styles.sendButton} type="submit" disabled={running}>
            {running ? "等待后端响应…" : "发送请求"} <span>↗</span>
          </button>
        </form>

        <section className={styles.responsePanel}>
          <div className={styles.panelTitle}>
            <div>
              <span>RESPONSE</span>
              <h2>原始响应</h2>
            </div>
            {selected ? (
              <div className={styles.metrics}>
                <strong className={selected.status < 400 ? styles.ok : styles.bad}>
                  {selected.status}
                </strong>
                <span>{selected.duration} ms</span>
              </div>
            ) : null}
          </div>

          {selected ? (
            <>
              <div className={styles.responseActions}>
                <code>{selected.method} {selected.path}</code>
                <button type="button" onClick={() => void copyCurl()}>
                  {copied ? "已复制" : "复制 cURL"}
                </button>
              </div>
              <details>
                <summary>响应头</summary>
                <pre>{selected.headers || "（无响应头）"}</pre>
              </details>
              <pre className={styles.responseBody}>{selected.body || "（空响应体）"}</pre>
            </>
          ) : (
            <div className={styles.emptyResponse}>
              <span>200</span>
              <h3>选择预设或构造一次请求</h3>
              <p>响应状态、耗时、headers 和 body 会完整显示在这里。</p>
            </div>
          )}
        </section>

        <aside className={styles.historyPanel}>
          <div className={styles.historyTitle}>
            <span>HISTORY</span>
            <button type="button" onClick={() => setHistory([])} disabled={!history.length}>
              清空
            </button>
          </div>
          {history.length ? (
            history.map((item) => (
              <button
                type="button"
                key={item.id}
                className={item.id === selected?.id ? styles.activeHistory : ""}
                onClick={() => {
                  setSelectedId(item.id);
                  setCopied(false);
                }}
              >
                <span className={item.status < 400 ? styles.okDot : styles.badDot} />
                <strong>{item.method}</strong>
                <code>{item.path}</code>
                <small>{item.duration} ms</small>
              </button>
            ))
          ) : (
            <p>还没有请求记录。</p>
          )}
        </aside>
      </section>
    </main>
  );
}

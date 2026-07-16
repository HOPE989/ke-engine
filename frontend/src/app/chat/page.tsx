"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { listConversations, listMessages, streamCompletion } from "./api";
import { Composer, ConversationList, MessageBubble } from "./components";
import type { ChatMessage, Conversation } from "./types";
import styles from "./chat.module.css";

export default function ChatPage() {
  const [identityInput, setIdentityInput] = useState("local-tester");
  const [userId, setUserId] = useState("local-tester");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messageEndRef = useRef<HTMLDivElement>(null);

  const refreshConversations = useCallback(async () => {
    setLoadingList(true);
    try {
      const page = await listConversations(userId);
      setConversations(page.items);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "会话列表加载失败");
    } finally {
      setLoadingList(false);
    }
  }, [userId]);

  const openConversation = useCallback(
    async (conversationId: string) => {
      setSelectedId(conversationId);
      setLoadingMessages(true);
      setError(null);
      try {
        const page = await listMessages(userId, conversationId);
        setMessages(page.items);
      } catch (caught) {
        setMessages([]);
        setError(caught instanceof Error ? caught.message : "消息历史加载失败");
      } finally {
        setLoadingMessages(false);
      }
    },
    [userId]
  );

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function applyIdentity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = identityInput.trim();
    if (!normalized || normalized === userId) return;
    setUserId(normalized);
    setSelectedId(null);
    setMessages([]);
    setError(null);
  }

  async function sendMessage() {
    const content = draft.trim();
    if (!content || sending) return;

    const stamp = Date.now();
    const userMessage: ChatMessage = {
      id: `local-user-${stamp}`,
      role: "USER",
      content,
      created_at: new Date().toISOString()
    };
    const assistantId = `local-assistant-${stamp}`;
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "ASSISTANT",
      content: "",
      created_at: new Date().toISOString(),
      pending: true
    };
    let resolvedConversationId = selectedId;

    setMessages((current) => [...current, userMessage, assistantMessage]);
    setDraft("");
    setSending(true);
    setError(null);

    try {
      await streamCompletion({
        userId,
        conversationId: selectedId,
        content,
        onMetadata: (conversationId) => {
          resolvedConversationId = conversationId;
          setSelectedId(conversationId);
        },
        onDelta: (delta) => {
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? { ...item, content: item.content + delta }
                : item
            )
          );
        }
      });
      if (resolvedConversationId) {
        await openConversation(resolvedConversationId);
      }
      await refreshConversations();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "消息发送失败";
      setError(message);
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                content: item.content || message,
                pending: false,
                failed: true
              }
            : item
        )
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <main className={styles.shell}>
      <ConversationList
        conversations={conversations}
        selectedId={selectedId}
        loading={loadingList}
        disabled={sending}
        onSelect={(id) => void openConversation(id)}
        onNew={() => {
          setSelectedId(null);
          setMessages([]);
          setError(null);
        }}
        onRefresh={() => void refreshConversations()}
      />

      <section className={styles.workspace}>
        <header className={styles.topbar}>
          <div>
            <span className={styles.eyebrow}>STREAMING COMPLETION</span>
            <h1>{selectedId ? `会话 #${selectedId}` : "新会话"}</h1>
          </div>
          <form className={styles.identity} onSubmit={applyIdentity}>
            <label htmlFor="mock-user">模拟用户</label>
            <input
              id="mock-user"
              value={identityInput}
              onChange={(event) => setIdentityInput(event.target.value)}
              disabled={sending}
            />
            <button type="submit" disabled={sending || !identityInput.trim()}>
              应用
            </button>
          </form>
        </header>

        <div className={styles.statusStrip} role="status">
          <span className={styles.statusDot} />
          身份 <strong>{userId}</strong>
          <span className={styles.statusDivider}>/</span>
          {sending ? "SSE 流接收中" : "等待请求"}
        </div>

        <div className={styles.messageArea} aria-live="polite">
          {loadingMessages ? (
            <div className={styles.loadingState}>正在读取消息历史…</div>
          ) : messages.length === 0 ? (
            <div className={styles.welcome}>
              <span className={styles.welcomeIndex}>01</span>
              <h2>连接后端，开始一轮真实对话。</h2>
              <p>
                页面会消费 <code>metadata</code>、<code>content_delta</code> 和终态事件，
                并在完成后重新读取服务端消息记录。
              </p>
              <div className={styles.suggestions}>
                {["介绍一下这个知识引擎", "给我一个简短的测试回答", "解释当前 Chat 链路"].map(
                  (text) => (
                    <button type="button" key={text} onClick={() => setDraft(text)}>
                      {text} <span aria-hidden="true">→</span>
                    </button>
                  )
                )}
              </div>
            </div>
          ) : (
            <div className={styles.messages}>
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
              <div ref={messageEndRef} />
            </div>
          )}
        </div>

        {error ? (
          <div className={styles.errorBanner} role="alert">
            <strong>请求异常</strong>
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="关闭错误提示">
              ×
            </button>
          </div>
        ) : null}

        <footer className={styles.composerWrap}>
          <Composer
            value={draft}
            sending={sending}
            onChange={setDraft}
            onSubmit={() => void sendMessage()}
          />
          <p>POST /api/v1/chat/completions · X-Mock-User-Id: {userId}</p>
        </footer>
      </section>
    </main>
  );
}

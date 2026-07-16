import type { KeyboardEvent } from "react";

import type { ChatMessage, Conversation } from "./types";
import styles from "./chat.module.css";

function shortDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function ConversationList(props: {
  conversations: Conversation[];
  selectedId: string | null;
  loading: boolean;
  disabled: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRefresh: () => void;
}) {
  return (
    <aside className={styles.sidebar} aria-label="会话列表">
      <div className={styles.brand}>
        <span className={styles.brandMark}>KE</span>
        <div>
          <strong>Chat Console</strong>
          <span>后端联调终端</span>
        </div>
      </div>

      <button
        className={styles.newButton}
        type="button"
        onClick={props.onNew}
        disabled={props.disabled}
      >
        <span aria-hidden="true">＋</span> 新建会话
      </button>

      <div className={styles.listHeader}>
        <span>最近会话</span>
        <button
          type="button"
          onClick={props.onRefresh}
          disabled={props.loading || props.disabled}
          aria-label="刷新会话列表"
        >
          {props.loading ? "···" : "↻"}
        </button>
      </div>

      <div className={styles.conversationList}>
        {!props.loading && props.conversations.length === 0 ? (
          <p className={styles.emptyList}>还没有会话。发送第一条消息后，这里会自动出现记录。</p>
        ) : null}
        {props.conversations.map((item) => (
          <button
            className={item.id === props.selectedId ? styles.selectedConversation : ""}
            type="button"
            key={item.id}
            onClick={() => props.onSelect(item.id)}
            disabled={props.disabled}
          >
            <strong>{item.title || "未命名会话"}</strong>
            <span>
              #{item.id} · {shortDate(item.updated_at)}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role.toUpperCase() === "USER";
  return (
    <article
      className={`${styles.message} ${isUser ? styles.userMessage : styles.assistantMessage}`}
      aria-label={isUser ? "用户消息" : "助手消息"}
    >
      <div className={styles.messageMeta}>
        <span>{isUser ? "YOU" : "KE ENGINE"}</span>
        {message.pending ? <span className={styles.live}>生成中</span> : null}
        {message.failed ? <span className={styles.failed}>失败</span> : null}
      </div>
      <p>{message.content || (message.pending ? "正在连接模型…" : "（空响应）")}</p>
    </article>
  );
}

export function Composer(props: {
  value: string;
  sending: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      props.onSubmit();
    }
  }

  return (
    <div className={styles.composer}>
      <textarea
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入消息，Enter 发送，Shift + Enter 换行"
        aria-label="消息内容"
        rows={3}
        disabled={props.sending}
      />
      <button
        type="button"
        onClick={props.onSubmit}
        disabled={props.sending || !props.value.trim()}
        aria-label="发送消息"
      >
        {props.sending ? "传输中" : "发送"}
        <span aria-hidden="true">↗</span>
      </button>
    </div>
  );
}

import Link from "next/link";

export function TestNav({ current }: { current: "document" | "chat" | "console" }) {
  const items = [
    { id: "document", href: "/", label: "文档流水线" },
    { id: "chat", href: "/chat", label: "Chat 流式会话" },
    { id: "console", href: "/console", label: "接口实验室" }
  ] as const;

  return (
    <nav className="test-nav" aria-label="后端测试入口">
      {items.map((item) => (
        <Link
          key={item.id}
          href={item.href}
          aria-current={current === item.id ? "page" : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

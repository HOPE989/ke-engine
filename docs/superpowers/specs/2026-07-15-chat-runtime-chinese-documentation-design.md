# Chat 运行时中文注释增强设计

## 背景与目标

`add-production-chat-langgraph-runtime` 已完成实现和验证，但核心流程目前多为简短的一行 docstring。后续维护者需要同时理解业务消息、LangGraph checkpoint、SSE producer 和应用生命周期之间的边界，单纯阅读代码容易误把这些资源或事务合并。

本次只增强代码内文档，不改变接口、控制流、异常处理、数据模型或运行配置。目标是让维护者能够从中文 docstring 和少量关键注释中快速回答“这个组件负责什么”“步骤为何按此顺序执行”“失败或断连时保留什么状态”。

## 覆盖范围

采用核心链路覆盖方案，修改以下模块中的现有 docstring 和注释：

- `backend/app/domains/chat/services/runtime.py`：producer、subscriber、registry、终态和 ASSISTANT 提交边界。
- `backend/app/services/chat_api/deps.py`：启动资源顺序、Graph 编译时机和逆序释放。
- `backend/app/services/chat_api/router.py`：USER 事务、producer 注册、SSE 订阅与查询所有权。
- `backend/app/services/chat_api/streaming.py`：LangGraph 私有事件到公开 SSE payload 的投影边界。
- `backend/app/infrastructure/langgraph.py`：DSN 转换、独立连接池、`setup()` 与关闭语义。
- `backend/app/domains/chat/services/conversation.py`：首条消息建会话、标题生成和同事务 USER 持久化。
- `backend/app/domains/chat/repositories/*.py`：owner scope、keyset cursor 方向和稳定排序。
- `backend/app/domains/chat/graph/*.py` 与 `graph/nodes/llm.py`：Graph 拓扑、runtime context 和节点职责。

简单 DTO、ORM 字段、包级 `__init__.py` 不做逐项解释，避免把类型名称机械翻译成冗余注释。

## 注释规则

### 中文 docstring

公开类、公开函数和承担关键协议职责的私有辅助函数使用略详细的中文 docstring。内容按实际需要说明：

- 组件职责及明确不负责的内容；
- 参数、返回值或 yield 数据的业务含义；
- 可能影响调用方的异常、事务或资源生命周期；
- 与 OpenSpec 约束直接相关的边界，例如业务历史不从 checkpoint 读取。

不重复类型标注已经清楚表达的信息，也不承诺代码尚未实现的能力。

### 分步骤注释

只在包含多个有顺序约束的关键函数中使用 `步骤 1/2/3` 注释，主要覆盖：

1. Chat lifespan 的资源初始化与挂载；
2. completion route 的 USER 事务、producer 创建和 SSE 返回；
3. producer 的 metadata、Graph 消费、ASSISTANT 提交和终态发布；
4. registry shutdown 的停止接收、限时等待与取消收尾。

简单校验、字段映射和直接 return 不添加步骤编号。

### 关键原因解释

注释优先解释不能从语句本身看出的原因：

- USER 消息必须在 Graph 启动前提交，保证失败时仍保留已接受输入；
- metadata 必须先于模型调用，稳定返回会话和用户消息 ID；
- subscriber detach 不取消 producer，保证客户端断连后仍能完成并持久化回答；
- `completed` 只能在 ASSISTANT 事务提交后发布，作为持久化成功确认；
- checkpointer 使用独立 psycopg pool，但复用唯一 `DATABASE_URL`；
- 会话与消息使用不同方向的 keyset cursor，并始终附加 owner 条件。

## 测试与验证

继续遵循 RED → GREEN → REFACTOR：

1. 先增加文档结构测试，使用 AST 检查核心类/函数存在非空中文 docstring，并检查关键流程保留分步骤注释和边界关键词。
2. 运行新增测试，确认因当前文档不足而失败。
3. 只补充满足设计要求的 docstring 和注释，不改生产行为。
4. 重跑新增测试并确认通过。
5. 运行全部 Chat 测试、完整后端测试和 OpenSpec strict 校验。

文档测试只约束代表性的关键入口，不要求所有私有方法达到固定字数，避免以后正常重构被脆弱的文本断言阻塞。

## 非目标

- 不新增 heartbeat、replay、stop、archive、并发控制或幂等能力。
- 不改变 API schema、SSE payload、数据库表或 checkpoint 配置。
- 不把设计文档内容大段复制到每个函数。
- 不为了注释调整模块结构或抽象层次。

# Business Understanding 收尾状态

截至 2026-07-21，`feat/business-understanding` 已完成最终审查修复、粗粒度 conversation Redis 分布式锁、Prompt 契约补强、DeerFlow 风格 `Command(goto)` 控制流纠偏和全量复验。

## 当前状态

- 分支：`feat/business-understanding`
- merge-base：`f132c5f5ff7ae9ede9233265377721ddb8b535e7`
- 远端：本轮收尾提交尚未 push；本地分支领先 `origin/feat/business-understanding`
- OpenSpec：`add-business-understanding` 为 `ready`，93/93 tasks 完成，strict validation 通过
- 工作区：最终证据提交后应为干净状态
- 尚未执行：OpenSpec archive、push、PR 或 merge；这些需要用户选择，不应自动进行

## 本轮最终修复

- 使用 `python-redis-lock` 和 `chat:conversation:{conversation_id}:completion` 粗粒度锁串行化同一 conversation 的整次 completion。
- existing conversation 先做 owner scope 查询，再观察锁状态；missing 与 foreign-owned 继续统一返回 404。
- 锁在 USER 落库前非阻塞获取；冲突返回 409，Redis 不可用时 fail closed 返回 503，两者都不写 USER、不访问 Graph。
- 锁 ownership 从请求事务转移给 `CompletionProducerRegistry`，覆盖 checkpoint inspect/resume、Graph、ASSISTANT commit 与 terminal；客户端断连不释放，后台 success/error/cancel/shutdown 的 `finally` 释放。
- Chat lifespan 共享 Redis client，关闭顺序为 Registry → Redis → PostgreSQL saver → 业务数据库。
- Prompt `v1` 明确唯一上下文继承、“按实际版呢”多轮规则、不得臆造，以及 BUSINESS/NON_BUSINESS/CLARIFY 三路合法 JSON 示例。
- `business_understanding` 通过 typed `Command(update, goto)` 原子提交结构化结果并跳转 BUSINESS/NON_BUSINESS/CLARIFY；clarify resume 同样以 `Command(goto="business_understanding")` 回到重评。Builder 已移除显式条件边和 clarification 静态回边。

关键提交：

- `925bf18` docs(openspec): require coarse chat completion lock
- `05ba96a` docs: plan chat conversation lock implementation
- `a1262ae` feat(chat): add conversation completion lock
- `4dcc6aa` fix(chat): serialize conversation completions
- `6ffa206` feat(chat): inject completion redis lock
- `672e647` fix(chat): clarify business prompt context rules

## 最终验证证据

- 真实 Redis：1 passed，6 deselected；同会话互斥、不同会话隔离、释放后可重取
- Command(goto) 聚焦回归：81 passed
- PostgreSQL integration：5 passed
- 后端非 integration：581 passed，3 skipped，6 deselected
- 离线确定性评测：3 passed；18 cases；`live_model=false`；五维全部通过
- 前端：11/11；lint exit 0；Next.js 15.5.19 build exit 0
- OpenSpec strict：通过
- `git diff --check`：通过

## 明确延期

用户确认本轮先不扩展边界复杂度。以下内容未作为当前 change 的 blocker：

- checkpoint 与业务数据库之间的跨存储原子补偿或 attempt/fencing 状态机；
- 对伪造 interrupt envelope 的额外类型/来源强化；
- entity 空白字符串统一规范化；
- live-model / 跨模型准确率评测；当前 18/18 只属于 deterministic contract/evaluator validation；
- 业务 RAG、SQL Tool、引用、证据校验和更细粒度业务意图。

## 后续可选动作

实现已经完成。下一步只需由用户选择：保留分支、push/开 PR、合并，或在合并策略明确后归档 OpenSpec；不要在未获选择前自动 archive。

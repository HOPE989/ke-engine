# Chat Runtime 源码注释增强设计

## 目标

在不改变任何运行逻辑、接口、类型和测试行为的前提下，增强以下文件的中文源码注释：

- `backend/app/domains/chat/services/runtime.py`
- `backend/app/services/chat_api/router.py`

注释应帮助不了解当前实现的开发者理解一次 Chat completion 从 HTTP 请求进入，到后台生成、实时推送、最终持久化以及连接断开后的完整生命周期。

## 注释原则

采用分层注释，而不是逐行翻译 Python 语法：

1. 文件级 docstring 描述模块边界以及两个文件之间的协作关系。
2. 类级 docstring 说明对象由谁创建、由谁持有、负责什么以及不负责什么。
3. 方法级 docstring 说明输入、关键副作用和生命周期语义。
4. 只在容易误解的语句附近增加行内注释，不解释显而易见的赋值和控制结构。
5. 保留现有公开名称、控制流、异常处理和事件顺序。

## `runtime.py` 注释内容

### 整体模型

文件顶部说明该模块由四个协作角色组成：

- `_CompletionChannel`：单次 completion 的进程内事件队列，同时充当 Producer 的 publisher。
- `CompletionSubscriber`：HTTP SSE 连接持有的消费端句柄。
- `CompletionProducerRegistry`：后台任务的所有者，负责启动、跟踪和关闭任务。
- `CompletionProducer`：执行 Graph、发布事件并保存完整 ASSISTANT 消息。

明确指出 Producer 和 Subscriber 引用同一个 `_CompletionChannel`，因此 Producer 对 `publish()` 的调用会进入 Subscriber 随后读取的同一个队列。

### Channel 与 Subscriber

补充说明：

- `asyncio.Queue` 在这里是同一 Python 进程内的异步通信工具，不是消息中间件。
- `maxsize=16` 提供有限背压；连接仍附着时，生产速度过快会等待消费者。
- `attached=False` 后不再入队，避免断开的客户端造成无人消费的数据累积。
- `detach()` 只改变 Channel 状态，不持有也不取消 Graph task。

### Registry

重点解释 `start()` 的实际展开过程：

1. 创建 `channel`。
2. 用同一个 `channel` 创建 `subscriber`。
3. 执行 `producer_factory(channel)`。
4. Router 中 lambda 的第一个形参因此接收到该 `channel`，再把它作为 `publisher` 传入 `CompletionProducer`。
5. 使用 `asyncio.create_task()` 启动 Producer，并由 Registry 的 `_tasks` 集合持有任务。

说明请求协程只持有 Subscriber，后台任务归 Registry 所有，因此 HTTP 连接取消不会自然传播成 Producer task 的取消。

对 `shutdown()` 说明拒绝新任务、限时等待、取消超时任务以及收集取消结果的顺序。

### Producer

按事件时序解释：

1. 先发布 `metadata`，让客户端尽早得到稳定业务 ID。
2. 调用 LangGraph，并把认可的模型事件投影成 `content_delta`。
3. 一边推送增量，一边在内存中拼接完整回答。
4. Graph 完成后，在独立事务中保存 ASSISTANT 消息。
5. 只有事务提交成功后才发布 `completed`。
6. Graph 或数据库失败时发布脱敏的统一 `error`，不保存部分回答。

补充说明 `thread_id` 使用 conversation ID 的原因，以及 `user_id` 当前保留但未参与查询的边界。

## `router.py` 注释内容

文件顶部增加 transport 层与 runtime 层的关系，并围绕 `create_completion()` 解释：

1. FastAPI 从请求体、认证依赖和应用 lifespan 依赖中准备参数。
2. `accept_user_turn()` 先提交 USER 消息；失败时不能创建后台 Producer。
3. `producer_registry.start()` 接收一个工厂函数，而不是现成 Producer，因为 Channel 必须由 Registry 先创建。
4. lambda 参数 `publisher` 是位置形参；Registry 调用 `producer_factory(channel)` 时，它得到的就是该 Channel。
5. `event_stream()` 循环从 Subscriber 读取事件并编码为 SSE。
6. 收到终态事件后退出；连接取消或异常也会进入 `finally` 并执行 `detach()`。
7. `detach()` 只解除实时订阅，后台生成和最终落库继续进行。

## 行为约束

本次变更不得：

- 修改任何函数签名、类型标注或导入。
- 修改事件名称、事件顺序、队列大小或关闭超时。
- 修改 Graph 配置、数据库事务或异常边界。
- 重命名 `publisher`、`channel` 等变量。
- 为注释改动新增或调整测试逻辑。

## 验证

修改完成后执行：

```text
pytest backend/tests/test_chat_completion_api.py \
       backend/tests/test_chat_completion_disconnect.py \
       backend/tests/test_chat_completion_producer.py
```

并检查 Git diff，确认只有注释和 docstring 发生变化。

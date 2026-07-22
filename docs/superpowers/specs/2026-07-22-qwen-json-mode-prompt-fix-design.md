# Qwen JSON Mode Prompt 修复设计

## 背景

业务理解节点通过 `ChatOpenAI.with_structured_output(BusinessUnderstandingResult)` 请求结构化输出。当前运行模型为阿里云百炼 OpenAI 兼容端点上的 `qwen3.6-flash`。该端点在使用 `response_format` 的 `json_object` 模式时，要求至少一条消息显式包含不区分大小写的 `json` 关键词。

现有业务理解系统 Prompt 包含 JSON 对象示例，但没有出现 `JSON` 关键词，因此任意输入在首个业务理解节点都可能被模型服务以 `invalid_parameter_error` 拒绝。

## 方案

保留现有 Pydantic 契约、`with_structured_output` 调用和业务路由，仅将系统 Prompt 的输出约束改为明确要求“仅以 JSON 格式返回结构化契约允许的字段”。

不显式改用 `json_mode`，因为当前适配层已经向服务端发出 JSON Mode 请求，缺失的是供应商要求的提示词关键词。不改用 function calling，避免改变当前模型协议及解析路径。

## 测试

在现有业务理解 Prompt 测试中增加回归断言，要求系统 Prompt 包含不区分大小写的 `json` 关键词。测试必须先在现有实现上因关键词缺失而失败，再修改 Prompt 使其通过。

随后运行业务理解节点相关测试与后端完整测试，确认路由、结构化结果和其他行为不变。

## 验收标准

- 业务理解系统 Prompt 显式包含 `JSON`。
- 原有字段约束和“不得输出 Markdown”要求保持不变。
- 新回归测试在修复前失败、修复后通过。
- 后端完整测试通过。
- 不修改 LangSmith、Langfuse、模型或环境变量配置。

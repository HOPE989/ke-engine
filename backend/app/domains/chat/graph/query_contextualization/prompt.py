import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.domains.chat.graph.query_contextualization.models import (
    QueryContextInput,
)


QUERY_CONTEXTUALIZATION_PROMPT_VERSION = "v3"

QUERY_CONTEXTUALIZATION_SYSTEM_PROMPT = """# Role

你是 Chat 服务的对话问题上下文化器。你的任务是把当前问题还原为一条脱离会话
历史也能理解的 standalone query，供下游 RAG 服务检索。

# Input Priority

original_query 是当前问题，优先于历史和业务上下文中的冲突值。
conversation_context 只用于补全能够唯一确定的指代、省略和上下文条件。
business_context 只用于消歧，不得覆盖当前问题的显式表达。

# Rules

1. 只生成一条 standalone query。
2. 补全由输入唯一确定的对象、条件和指代。
3. 删除问候、礼貌用语、重复表达和不改变信息需求的口语噪声。
4. 可以规范明确的错别字、别名和业务术语。
5. 必须保留会改变答案的实体、时间、数字、范围、否定、比较、归属和版本。
6. 当前问题已经独立、简洁、规范时，保持语义稳定并允许原样返回。
7. 输入不能唯一确定的信息不得臆造；无法可靠改写时完整返回 original_query。

# Prohibitions

- 不得回答问题。
- 不得拆分问题或生成关键词列表。
- 不得选择 Retriever。
- 不得生成 SQL。
- 不得生成 Cypher。
- 不得输出解释、理由、置信度或 Markdown。

只按结构化输出 Schema 返回 standalone_query。"""


def build_query_contextualization_messages(
    request: QueryContextInput,
) -> list[BaseMessage]:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [
        SystemMessage(content=QUERY_CONTEXTUALIZATION_SYSTEM_PROMPT),
        HumanMessage(content=f"INPUT_JSON\n{payload}"),
    ]

import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.domains.rag.graph.query_rewrite.models import QueryRewriteInput


QUERY_REWRITE_PROMPT_VERSION = "v1"

QUERY_REWRITE_SYSTEM_PROMPT = """# Role

你是 RAG 检索查询改写器。你的任务是把当前问题改写为一条脱离会话历史也能理解、
适合送入后续 RAG 检索管线的 standalone query。

# Input Priority

输入包含 original_query、conversation_context 和 business_context。
original_query 是当前问题；当前问题优先于历史和业务上下文中的冲突值。
conversation_context 只用于补全能够唯一确定的指代和省略。
business_context 只用于消歧，不得覆盖当前问题的显式表达。

# Rewrite Rules

1. 只生成一条 standalone query。
2. 补全由输入唯一确定的对象、条件和指代。
3. 删除问候、礼貌用语、重复表达和不改变信息需求的口语噪声。
4. 可以规范明确的错别字、别名和业务术语；例如“货运单”规范为“运单”。
5. 必须保留会改变检索结果的实体、时间、数字、范围、否定、比较、归属和版本。
6. 当前问题已经独立、简洁、规范时，保持语义稳定并允许原样返回。
7. 输入不能唯一确定的信息不得臆造，也不得用常识补充不存在的事实。

# Prohibitions

- 不得回答用户问题。
- 不得拆分为多个问题、多个查询、研究步骤或关键词列表。
- 不得选择 Retriever 或给出路由结论。
- 不得生成 SQL。
- 不得生成 Cypher。
- 不得输出解释、理由、置信度或 Markdown。

只按结构化输出 Schema 返回 standalone_query。"""


def build_query_rewrite_messages(
    request: QueryRewriteInput,
) -> list[BaseMessage]:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [
        SystemMessage(content=QUERY_REWRITE_SYSTEM_PROMPT),
        HumanMessage(content=f"INPUT_JSON\n{payload}"),
    ]

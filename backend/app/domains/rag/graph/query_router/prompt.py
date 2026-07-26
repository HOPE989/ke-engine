import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.domains.rag.graph.query_router.models import QueryRouterInput


QUERY_ROUTER_PROMPT_VERSION = "v1"

QUERY_ROUTER_SYSTEM_PROMPT = """# Role

你是 RAG 检索器路由器。根据回答问题所需的权威证据源，从
available_retrievers 中选择一个或多个检索器，并选择最小充分集合。

# Retriever Boundaries

- DOCUMENT_HYBRID：规则、制度、流程、定义、说明和其他非结构化知识。
- SQL：业务事实、状态、明细、计数、聚合、筛选和比较。
- GRAPH：已建模实体之间的拓扑、路径、可达性、依赖和关系。

# Routing Rules

1. 只选择 available_retrievers 中的能力。
2. 一个问题需要多种独立证据源时选择一个或多个检索器。
3. 不得默认全选或为了保险增加能力，输出顺序不表示优先级。
4. 按权威证据源判断，不按表面关键词判断；例如“规程规定限值是多少”仍属于文档，
   仅出现“关系”也不代表一定需要图谱。
5. routing_reason 只简短说明所需证据类型，不回答问题。

# Prohibitions

- 不得回答用户问题。
- 不得改写或拆分查询。
- 不得生成 SQL。
- 不得生成 Cypher。
- 不得输出每路查询、置信度、连接参数、Markdown 或额外字段。

只按结构化输出 Schema 返回 selected_retrievers 和 routing_reason。"""


def build_query_router_messages(
    request: QueryRouterInput,
) -> list[BaseMessage]:
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [
        SystemMessage(content=QUERY_ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=f"INPUT_JSON\n{payload}"),
    ]

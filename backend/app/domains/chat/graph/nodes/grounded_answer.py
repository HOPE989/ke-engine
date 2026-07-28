"""仅依据 RAG 返回证据生成带编号引用的回答。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.state import ChatState
from app.domains.rag.services import EvidencePackage

EMPTY_EVIDENCE_ANSWER = "未检索到相关依据。"
GROUNDED_ANSWER_SYSTEM_PROMPT = """你是企业文档问答助手。
只能使用用户消息中给出的编号证据回答，不得补充外部知识或猜测。
事实陈述必须使用与证据顺序对应的 [1]、[2] 等编号引用。
如果证据不足以回答，应明确说明依据不足。"""


async def grounded_answer_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, list[BaseMessage]]:
    return await invoke_grounded_answer(state, model=runtime.context.model)


async def invoke_grounded_answer(
    state: ChatState,
    *,
    model: BaseChatModel,
) -> dict[str, list[BaseMessage]]:
    package = EvidencePackage.model_validate(state.get("evidence_package"))
    if not package.evidence_items:
        return {"messages": [AIMessage(content=EMPTY_EVIDENCE_ANSWER)]}
    message = await model.ainvoke(
        build_grounded_answer_messages(state, package)
    )
    return {"messages": [message]}


def build_grounded_answer_messages(
    state: ChatState,
    package: EvidencePackage,
) -> list[BaseMessage]:
    question = next(
        (
            message.content
            for message in reversed(state["messages"])
            if isinstance(message, HumanMessage)
            and isinstance(message.content, str)
        ),
        package.query,
    )
    evidence = "\n\n".join(
        (
            f"[{index}] 文档={item.file_name or item.doc_id} "
            f"citationId={item.citation_id}\n{item.content}"
        )
        for index, item in enumerate(package.evidence_items, start=1)
    )
    return [
        SystemMessage(content=GROUNDED_ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=f"问题：{question}\n\n证据：\n{evidence}"),
    ]

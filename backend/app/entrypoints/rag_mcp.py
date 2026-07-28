"""固定本地地址的文档 RAG MCP 进程入口。"""

from app.core.config import create_settings, validate_chat_startup_settings
from app.domains.rag.services import RetrieveEvidenceService
from app.infrastructure.rag_runtime import create_compiled_rag_graph
from app.services.rag_mcp import create_rag_mcp_server


def create_server():
    settings = validate_chat_startup_settings(create_settings())
    graph = create_compiled_rag_graph(settings)
    return create_rag_mcp_server(RetrieveEvidenceService(graph))


def main() -> None:
    create_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()

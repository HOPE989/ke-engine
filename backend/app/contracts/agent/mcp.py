"""Agent MCP 工具契约类型。"""

from pydantic import BaseModel


class ToolInvocation(BaseModel):
    """Agent 调用 MCP/内部工具的稳定输入形状。"""

    tool_name: str
    arguments: dict

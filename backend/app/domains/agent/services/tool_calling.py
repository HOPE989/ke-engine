"""Agent 工具调用服务。"""


async def call_tool(tool_name: str, arguments: dict) -> dict:
    """调用内部工具的占位入口。"""

    return {"tool_name": tool_name, "arguments": arguments}

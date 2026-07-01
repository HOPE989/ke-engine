"""MinerU PDF 转换接口的最小调用封装。"""

from typing import Any

from app.modules.document.errors import DocumentConversionFailed


async def request_mineru_zip(
    *,
    client: Any,
    filename: str,
    content: bytes,
) -> bytes:
    """调用 MinerU `/file_parse` 并返回 ZIP 响应内容。"""

    try:
        # 第一版同步等待 MinerU 返回 ZIP，后台任务不在本变更范围内。
        response = await client.post(
            "/file_parse",
            files={"file": (filename, content, "application/pdf")},
            data={
                "output_format": "zip",
                "return_images": True,
            },
        )
        response.raise_for_status()
    except Exception as exc:
        raise DocumentConversionFailed() from exc
    return response.content

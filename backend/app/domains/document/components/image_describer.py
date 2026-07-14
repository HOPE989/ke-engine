"""文档图片描述模型适配。"""

import base64
from typing import Any

from langchain_core.messages import HumanMessage


class RuntimeImageDescriber:
    """使用启动期注入的多模态模型生成文档图片描述。"""

    def __init__(self, *, model: Any) -> None:
        self._model = model

    async def describe_image(self, *, filename: str, content: bytes, content_type: str) -> str:
        """调用图片理解模型，返回一条中文图片描述。"""

        encoded = base64.b64encode(content).decode("ascii")
        response = await self._model.ainvoke(
            [
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": f"请用一句简洁中文描述图片 {filename} 的主要内容。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{encoded}",
                            },
                        },
                    ],
                )
            ]
        )
        return str(response.content)

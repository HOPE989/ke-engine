"""文档模块启动期运行时资源集合。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DocumentRuntime:
    """聚合文档上传请求需要复用的启动期资源。"""

    repository: Any
    storage: Any
    file_detector: Any
    id_generator: Any
    conversion_dispatcher: Any
    embed_store_dispatcher: Any
    redis_client: Any

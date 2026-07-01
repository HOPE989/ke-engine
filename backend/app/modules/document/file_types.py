"""基于 Magika 的文档文件类型识别。

只接受 PDF、Markdown，以及带受支持扩展名的通用文本文件。
"""

from enum import Enum
from pathlib import PurePath
from typing import Any

from app.modules.document.errors import (
    FileTypeDetectionFailed,
    UnsupportedDocumentFileType,
)

SUPPORTED_TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
TEXT_LABELS = {"markdown", "md", "txt", "text", "plain text"}
TEXT_MIME_TYPES = {"text/markdown", "text/x-markdown", "text/plain"}


class DocumentFileType(str, Enum):
    """文档上传工作流当前支持的业务文件类型。"""

    PDF = "pdf"
    PLAIN_TEXT = "plain_text"


def _normalized_output_value(output: Any, name: str) -> str:
    """读取 Magika output 字段并归一化为小写字符串。"""

    value = getattr(output, name, "") or ""
    return str(value).strip().lower()


def detect_document_file_type(
    *,
    filename: str,
    content: bytes,
    magika_client: Any,
) -> DocumentFileType:
    """检测上传内容的业务文件类型，失败时抛出稳定领域异常。"""

    try:
        result = magika_client.identify_bytes(content)
    except Exception as exc:
        raise FileTypeDetectionFailed() from exc

    output = getattr(result, "output", result)
    ct_label = _normalized_output_value(output, "ct_label")
    mime_type = _normalized_output_value(output, "mime_type")

    # 1. PDF 既接受内容标签，也接受 MIME 类型命中。
    if ct_label == "pdf" or mime_type == "application/pdf":
        return DocumentFileType.PDF

    # 2. Markdown 被业务上归为 plain text，因为无需 PDF 转换。
    if ct_label in {"markdown", "md"} or mime_type in {"text/markdown", "text/x-markdown"}:
        return DocumentFileType.PLAIN_TEXT

    # 3. 通用 text 只有在扩展名明确受支持时才放行。
    suffix = PurePath(filename.lower()).suffix
    if suffix in SUPPORTED_TEXT_EXTENSIONS and (
        ct_label in TEXT_LABELS or mime_type in TEXT_MIME_TYPES or mime_type.startswith("text/")
    ):
        return DocumentFileType.PLAIN_TEXT

    raise UnsupportedDocumentFileType()

"""基于 Magika 的文档文件类型识别。

只接受 PDF、Word、Markdown，以及带受支持扩展名的通用文本文件。
"""

from enum import Enum
from pathlib import PurePath
from typing import Any

from app.domains.document.shared.errors import (
    FileTypeDetectionFailed,
    UnsupportedDocumentFileType,
)

SUPPORTED_TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
TEXT_LABELS = {"markdown", "md", "txt", "text", "plain text"}
TEXT_MIME_TYPES = {"text/markdown", "text/x-markdown", "text/plain"}
WORD_LABELS = {"doc", "docx", "word"}
WORD_MIME_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXCEL_LABELS = {"xls", "xlsx", "excel"}
EXCEL_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
CSV_LABELS = {"csv"}
CSV_MIME_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}


class DocumentFileType(str, Enum):
    """文档上传工作流当前支持的业务文件类型。"""

    PDF = "pdf"
    PLAIN_TEXT = "plain_text"
    WORD = "word"
    EXCEL = "excel"
    CSV = "csv"


def _normalized_output_value(output: Any, name: str) -> str:
    """读取 Magika output 字段并归一化为小写字符串。"""

    value = getattr(output, name, "") or ""
    return str(value).strip().lower()


def detect_document_file_type(
    *,
    filename: str,
    content: bytes,
    upload_content_type: str,
    magika_client: Any,
) -> DocumentFileType:
    """检测上传内容的业务文件类型，失败时抛出稳定领域异常。"""

    try:
        result = magika_client.identify_bytes(content)
    except Exception as exc:
        raise FileTypeDetectionFailed() from exc

    output = getattr(result, "output", result)
    ct_label = _normalized_output_value(output, "ct_label")
    detected_mime_type = _normalized_output_value(output, "mime_type")
    upload_mime_type = str(upload_content_type or "").strip().lower()
    suffix = PurePath(filename.lower()).suffix

    # 1. PDF 既接受上传 MIME，也接受 Magika 内容标签或 MIME 命中。
    if (
        upload_mime_type == "application/pdf"
        or ct_label == "pdf"
        or detected_mime_type == "application/pdf"
    ):
        return DocumentFileType.PDF

    # 2. Magika 明确识别为 Excel 时优先按 Excel 接受，避免被伪装的上传 MIME 覆盖。
    if ct_label in EXCEL_LABELS or detected_mime_type in EXCEL_MIME_TYPES:
        return DocumentFileType.EXCEL

    if upload_mime_type in EXCEL_MIME_TYPES and suffix in {".xls", ".xlsx"}:
        return DocumentFileType.EXCEL

    if suffix == ".csv" and (
        upload_mime_type in CSV_MIME_TYPES
        or upload_mime_type == "application/octet-stream"
        or detected_mime_type in CSV_MIME_TYPES
        or detected_mime_type in TEXT_MIME_TYPES
        or detected_mime_type.startswith("text/")
        or ct_label in TEXT_LABELS
        or ct_label in CSV_LABELS
    ):
        return DocumentFileType.CSV

    # 3. Word 需要明确 MIME 或 Magika 内容标签；不靠扩展名单独放行。
    if (
        upload_mime_type in WORD_MIME_TYPES
        or detected_mime_type in WORD_MIME_TYPES
        or ct_label in WORD_LABELS
    ):
        return DocumentFileType.WORD

    # 4. Markdown MIME 被业务上归为 plain text，因为无需 PDF 转换。
    if upload_mime_type in {"text/markdown", "text/x-markdown"}:
        return DocumentFileType.PLAIN_TEXT

    # 5. 通用上传文本 MIME 需要配合明确受支持的扩展名。
    if suffix in SUPPORTED_TEXT_EXTENSIONS and (
        upload_mime_type in TEXT_MIME_TYPES or upload_mime_type.startswith("text/")
    ):
        return DocumentFileType.PLAIN_TEXT

    # 6. 保留 Magika 明确文本结论的兼容路径。
    if ct_label in {"markdown", "md"} or detected_mime_type in {
        "text/markdown",
        "text/x-markdown",
    }:
        return DocumentFileType.PLAIN_TEXT

    if suffix in SUPPORTED_TEXT_EXTENSIONS and (
        ct_label in TEXT_LABELS
        or detected_mime_type in TEXT_MIME_TYPES
        or detected_mime_type.startswith("text/")
    ):
        return DocumentFileType.PLAIN_TEXT

    raise UnsupportedDocumentFileType()

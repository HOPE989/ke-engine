"""文档上传请求与响应的数据结构。

本文件只处理请求边界处的轻量校验和传输对象，不触碰数据库或外部服务。
"""

from dataclasses import dataclass
from typing import Any

from fastapi import UploadFile

from app.domains.document.components.data_query_identifiers import is_valid_data_query_table_name
from app.domains.document.shared.models import KnowledgeBaseType


class InvalidDocumentUpload(Exception):
    """上传请求内容不合法时使用的内部校验异常。"""

    pass


class DocumentFileTooLarge(Exception):
    """上传文件超过配置大小上限时使用的内部校验异常。"""

    pass


class InvalidDocumentChunkRequest(Exception):
    """chunk 参数关系不合法时使用的内部校验异常。"""

    pass


UPLOAD_READ_CHUNK_SIZE_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidatedDocumentUpload:
    """通过 HTTP 边界校验后的上传文件数据。

    `table_name` 和 `is_override` 只在 DATA_QUERY spreadsheet 上传中有意义。
    DOCUMENT_SEARCH 即使传入这些字段，也会在校验阶段被规整为 `None/False`，
    避免普通文档链路误创建 table_meta 或触发 override。
    """

    doc_title: str
    safe_filename: str
    upload_user: str
    accessible_by: str
    description: str
    knowledge_base_type: str
    content_type: str
    content: bytes
    size_bytes: int
    table_name: str | None = None
    is_override: bool = False
    data_query_upload_lock_factory: Any | None = None


def validate_document_chunk_request(request: Any) -> Any:
    """校验 chunk_size 与 overlap 的业务关系。"""

    if request.chunk_size <= 0 or request.overlap < 0 or request.overlap >= request.chunk_size:
        raise InvalidDocumentChunkRequest()
    return request


def safe_upload_basename(filename: str | None) -> str:
    """从上传文件名中提取安全 basename，拒绝空文件名。"""

    raw_filename = (filename or "").strip()
    if not raw_filename:
        raise InvalidDocumentUpload()

    # 上传文件名可能携带路径，只保留最后一段，避免污染对象 key。
    basename = raw_filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
    if basename in {"", ".", ".."}:
        raise InvalidDocumentUpload()
    return basename


async def _read_upload_content_limited(
    *,
    file: UploadFile,
    max_size_bytes: int,
) -> bytes:
    """分块读取上传内容，超过限制后立即拒绝。"""

    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = await file.read(UPLOAD_READ_CHUNK_SIZE_BYTES)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size_bytes:
            raise DocumentFileTooLarge()
        chunks.append(chunk)

    return b"".join(chunks)


async def validate_document_upload(
    *,
    file: UploadFile,
    upload_user: str,
    accessible_by: str,
    description: str | None,
    knowledge_base_type: str,
    max_upload_size_mb: int,
    table_name: str | None = None,
    is_override: bool | None = None,
) -> ValidatedDocumentUpload:
    """校验 multipart 上传请求并返回不可变的上传数据对象。

    本函数只处理 HTTP 入参层面的通用规则：必填字段、文件名、大小、DATA_QUERY
    `tableName` 形状等。文件真实类型由 workflow 调用 Magika 后判断；数据库占位、
    对象存储和 Kafka 派发也都不在这里发生。
    """

    # 1. 先校验普通表单字段，避免空上传者或空访问范围入库。
    normalized_user = upload_user.strip()
    normalized_scope = accessible_by.strip()
    normalized_description = (description or "").strip()
    normalized_knowledge_base_type = (knowledge_base_type or "").strip()
    if not normalized_user or not normalized_scope:
        raise InvalidDocumentUpload()
    if normalized_knowledge_base_type not in {item.value for item in KnowledgeBaseType}:
        raise InvalidDocumentUpload()
    normalized_table_name = (table_name or "").strip()
    if normalized_knowledge_base_type == KnowledgeBaseType.DATA_QUERY.value:
        # DATA_QUERY 的 tableName 会进入逻辑表唯一约束和物理表名生成，因此在请求边界
        # 就完成字符集与长度校验，失败时不能触达 workflow。
        if not normalized_table_name or not is_valid_data_query_table_name(
            normalized_table_name
        ):
            raise InvalidDocumentUpload()
        upload_table_name = normalized_table_name
        upload_is_override = bool(is_override)
    else:
        # DOCUMENT_SEARCH 忽略 DATA_QUERY 专属字段，保持旧上传语义不变。
        upload_table_name = None
        upload_is_override = False

    # 2. 文件名校验早于读取内容，失败时不触发后续业务流程。
    safe_filename = safe_upload_basename(file.filename)
    max_size_bytes = max_upload_size_mb * 1024 * 1024
    try:
        content = await _read_upload_content_limited(
            file=file,
            max_size_bytes=max_size_bytes,
        )
    except DocumentFileTooLarge:
        raise
    except Exception as exc:
        raise InvalidDocumentUpload() from exc

    # 3. 内容大小在请求边界完成检查，workflow 只接收已验证字节。
    if not content:
        raise InvalidDocumentUpload()

    return ValidatedDocumentUpload(
        doc_title=safe_filename,
        safe_filename=safe_filename,
        upload_user=normalized_user,
        accessible_by=normalized_scope,
        description=normalized_description,
        knowledge_base_type=normalized_knowledge_base_type,
        content_type=(file.content_type or "").strip().lower(),
        content=content,
        size_bytes=len(content),
        table_name=upload_table_name,
        is_override=upload_is_override,
    )

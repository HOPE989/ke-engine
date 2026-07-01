"""文档上传请求与响应的数据结构。

本文件只处理请求边界处的轻量校验和传输对象，不触碰数据库或外部服务。
"""

from dataclasses import dataclass

from fastapi import UploadFile
from pydantic import BaseModel


class InvalidDocumentUpload(Exception):
    """上传请求内容不合法时使用的内部校验异常。"""

    pass


class DocumentFileTooLarge(Exception):
    """上传文件超过配置大小上限时使用的内部校验异常。"""

    pass


@dataclass(frozen=True, slots=True)
class ValidatedDocumentUpload:
    """通过 HTTP 边界校验后的上传文件数据。"""

    doc_title: str
    safe_filename: str
    upload_user: str
    accessible_by: str
    content_type: str
    content: bytes
    size_bytes: int


class DocumentMetadata(BaseModel):
    """文档上传成功后返回给客户端的稳定元数据。"""

    doc_id: str
    doc_title: str
    upload_user: str
    accessible_by: str
    doc_url: str | None
    converted_doc_url: str | None
    status: str


def document_metadata_from_record(record) -> DocumentMetadata:
    """把持久化记录转换为 API 元数据，避免 JSON 大整数精度风险。"""

    return DocumentMetadata(
        doc_id=str(record.doc_id),
        doc_title=record.doc_title,
        upload_user=record.upload_user,
        accessible_by=record.accessible_by,
        doc_url=record.doc_url,
        converted_doc_url=record.converted_doc_url,
        status=record.status,
    )


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


async def validate_document_upload(
    *,
    file: UploadFile,
    upload_user: str,
    accessible_by: str,
    max_upload_size_mb: int,
) -> ValidatedDocumentUpload:
    """校验 multipart 上传请求并返回不可变的上传数据对象。"""

    # 1. 先校验普通表单字段，避免空上传者或空访问范围入库。
    normalized_user = upload_user.strip()
    normalized_scope = accessible_by.strip()
    if not normalized_user or not normalized_scope:
        raise InvalidDocumentUpload()

    # 2. 文件名校验早于读取内容，失败时不触发后续业务流程。
    safe_filename = safe_upload_basename(file.filename)
    try:
        content = await file.read()
    except Exception as exc:
        raise InvalidDocumentUpload() from exc

    # 3. 内容大小在请求边界完成检查，workflow 只接收已验证字节。
    if not content:
        raise InvalidDocumentUpload()

    max_size_bytes = max_upload_size_mb * 1024 * 1024
    if len(content) > max_size_bytes:
        raise DocumentFileTooLarge()

    return ValidatedDocumentUpload(
        doc_title=safe_filename,
        safe_filename=safe_filename,
        upload_user=normalized_user,
        accessible_by=normalized_scope,
        content_type=(file.content_type or "").strip().lower(),
        content=content,
        size_bytes=len(content),
    )

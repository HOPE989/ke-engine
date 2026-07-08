"""Document HTTP 契约类型。"""

from pydantic import BaseModel, StrictInt


class DocumentMetadata(BaseModel):
    """文档上传成功后返回给客户端的稳定元数据。"""

    doc_id: str
    doc_title: str
    upload_user: str
    accessible_by: str
    doc_url: str | None
    converted_doc_url: str | None
    status: str


class DocumentChunkRequest(BaseModel):
    """文档切分请求体。"""

    chunk_size: StrictInt
    overlap: StrictInt


class DocumentChunkResponse(BaseModel):
    """文档切分成功后返回给客户端的稳定元数据。"""

    doc_id: str
    status: str
    segment_count: int

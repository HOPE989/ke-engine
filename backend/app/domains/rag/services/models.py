"""RAG 服务边界使用的最小请求与可扩展证据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.rag.graph.query_router import RetrieverKind
from app.domains.rag.graph.retrieval.models import (
    _normalized_nonblank_values,
)


class RetrieveEvidenceRequest(BaseModel):
    """可信内部调用方提交的一次文档证据检索请求。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    query: str = Field(min_length=1, pattern=r"\S")
    accessible_by: tuple[str, ...] = Field(alias="accessibleBy")
    doc_ids: tuple[str, ...] = Field(default=(), alias="docIds")
    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return value.strip()

    @field_validator("accessible_by", mode="before")
    @classmethod
    def validate_accessible_by(cls, value: object) -> tuple[str, ...]:
        return _normalized_nonblank_values(value)

    @field_validator("doc_ids", mode="before")
    @classmethod
    def validate_doc_ids(cls, value: object) -> tuple[str, ...]:
        if value in (None, (), []):
            return ()
        return _normalized_nonblank_values(value)


class EvidenceItem(BaseModel):
    """一条可供回答引用的最终重排文档证据。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    source_type: Literal["DOCUMENT"] = Field(
        default="DOCUMENT",
        alias="sourceType",
    )
    citation_id: str = Field(
        min_length=1,
        pattern=r"\S",
        alias="citationId",
    )
    content: str = Field(min_length=1, pattern=r"\S")
    doc_id: str = Field(min_length=1, pattern=r"\S", alias="docId")
    chunk_id: str = Field(min_length=1, pattern=r"\S", alias="chunkId")
    file_name: str | None = Field(
        default=None,
        min_length=1,
        pattern=r"\S",
        alias="fileName",
    )
    url: str | None = Field(default=None, min_length=1, pattern=r"\S")
    rerank_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        alias="rerankScore",
    )


class EvidencePackage(BaseModel):
    """RAG Graph 执行结果的最小稳定投影。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    query: str = Field(min_length=1, pattern=r"\S")
    selected_retrievers: tuple[RetrieverKind, ...] = Field(
        min_length=1,
        alias="selectedRetrievers",
    )
    evidence_items: tuple[EvidenceItem, ...] = Field(
        default=(),
        alias="evidenceItems",
    )

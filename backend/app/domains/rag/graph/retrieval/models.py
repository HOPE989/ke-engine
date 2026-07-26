"""文档检索在 LangGraph state 中使用的可序列化契约。"""

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.domains.rag.graph.query_router import RetrieverKind


def _normalized_nonblank_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("expected a collection of non-blank strings")
    normalized: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("values must be non-blank strings")
        normalized.add(item.strip())
    if not normalized:
        raise ValueError("at least one value is required")
    return tuple(sorted(normalized))


class DocumentRetrievalScope(BaseModel):
    """由服务端验证并绑定到单次请求的文档检索范围。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    accessible_by: tuple[str, ...] = Field(alias="accessibleBy")
    doc_ids: tuple[str, ...] = Field(default=(), alias="docIds")

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


class DocumentRetrievalOptions(BaseModel):
    """入口装配时注入的不可变 Hybrid 检索预算。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_limit: int = Field(default=10, ge=1)
    rank_window_size: int = Field(default=50, ge=1)
    rank_constant: Literal[60] = 60
    timeout_seconds: float = Field(default=10, gt=0)

    @model_validator(mode="after")
    def validate_rank_window(self) -> "DocumentRetrievalOptions":
        if self.rank_window_size < self.result_limit:
            raise ValueError("rank_window_size must be >= result_limit")
        return self


class DocumentCandidate(BaseModel):
    """从 LangChain Document 投影得到的领域候选。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    chunk_id: str = Field(
        min_length=1,
        pattern=r"\S",
        alias="chunkId",
    )
    doc_id: str = Field(
        min_length=1,
        pattern=r"\S",
        alias="docId",
    )
    text: str = Field(min_length=1, pattern=r"\S")
    source_metadata: dict[str, JsonValue] = Field(
        default_factory=dict,
        alias="sourceMetadata",
    )


class RetrievalStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class RetrievalDiagnostics(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    duration_ms: int = Field(ge=0, alias="durationMs")
    result_count: int = Field(ge=0, alias="resultCount")


class RetrievalOutcome(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    retriever_id: RetrieverKind = Field(alias="retrieverId")
    status: RetrievalStatus
    candidates: tuple[DocumentCandidate, ...] = ()
    diagnostics: RetrievalDiagnostics

    @model_validator(mode="after")
    def validate_status_and_count(self) -> "RetrievalOutcome":
        count = len(self.candidates)
        if self.diagnostics.result_count != count:
            raise ValueError("result_count must match candidates")
        if self.status is RetrievalStatus.SUCCESS and count == 0:
            raise ValueError("SUCCESS requires candidates")
        if self.status is not RetrievalStatus.SUCCESS and count:
            raise ValueError("only SUCCESS may contain candidates")
        return self

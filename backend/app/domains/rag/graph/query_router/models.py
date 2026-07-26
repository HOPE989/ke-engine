from enum import StrEnum
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field


class RetrieverKind(StrEnum):
    DOCUMENT_HYBRID = "DOCUMENT_HYBRID"
    SQL = "SQL"
    GRAPH = "GRAPH"


class RoutingDecisionSource(StrEnum):
    MODEL = "MODEL"
    FALLBACK = "FALLBACK"


class QueryRouterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standalone_query: str = Field(min_length=1, pattern=r"\S")
    available_retrievers: list[RetrieverKind] = Field(
        min_length=1,
        max_length=3,
    )


class QueryRouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_retrievers: list[RetrieverKind] = Field(
        min_length=1,
        max_length=3,
    )
    routing_reason: str = Field(min_length=1, pattern=r"\S")


class RetrievalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_retrievers: list[RetrieverKind] = Field(
        min_length=1,
        max_length=3,
    )
    routing_reason: str = Field(min_length=1, pattern=r"\S")
    decision_source: RoutingDecisionSource


class QueryRouterUpdate(TypedDict):
    retrieval_plan: dict[str, object]


class QueryRouterUnavailable(Exception):
    """Router 失败且没有安全 fallback 能力。"""

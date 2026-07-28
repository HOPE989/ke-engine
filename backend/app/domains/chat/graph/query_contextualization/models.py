from typing import Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConversationContextMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, pattern=r"\S")


class BusinessContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str | None = Field(default=None, pattern=r"\S")
    entities: dict[str, str] = Field(default_factory=dict)


class QueryContextInput(BaseModel):
    """Chat 将当前轮问题还原为脱离会话也能理解的独立问题。"""

    model_config = ConfigDict(extra="forbid")

    original_query: str = Field(min_length=1, pattern=r"\S")
    conversation_context: list[ConversationContextMessage] = Field(
        default_factory=list
    )
    business_context: BusinessContext | None = None

    @model_validator(mode="after")
    def reject_duplicated_current_query(self) -> Self:
        current_query = self.original_query.strip()
        if any(
            message.role == "user"
            and message.content.strip() == current_query
            for message in self.conversation_context
        ):
            raise ValueError(
                "conversation_context must not duplicate original_query"
            )
        return self


class QueryContextResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standalone_query: str = Field(
        min_length=2,
        pattern=r"\S",
        description="一条脱离会话历史也能完整理解的问题",
    )


class QueryContextUpdate(TypedDict):
    standalone_query: str

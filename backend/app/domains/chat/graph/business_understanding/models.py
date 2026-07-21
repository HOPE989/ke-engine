from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BusinessRoute(StrEnum):
    BUSINESS = "BUSINESS"
    NON_BUSINESS = "NON_BUSINESS"
    CLARIFY = "CLARIFY"


class BusinessIntent(StrEnum):
    POLICY_RULE_QA = "POLICY_RULE_QA"
    TRANSPORT_OPERATION_QA = "TRANSPORT_OPERATION_QA"
    COAL_SALES_QA = "COAL_SALES_QA"
    PROFESSIONAL_KNOWLEDGE_QA = "PROFESSIONAL_KNOWLEDGE_QA"
    BUSINESS_DATA_QUERY = "BUSINESS_DATA_QUERY"
    OTHER_BUSINESS = "OTHER_BUSINESS"


class BusinessEntities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_plan_no: str | None = None
    train_no: str | None = None
    formation_no: str | None = None
    contract_no: str | None = None
    document_type: str | None = None
    document_no: str | None = None
    customer: str | None = None
    supplier: str | None = None
    coal_type: str | None = None
    departure_station: str | None = None
    arrival_station: str | None = None
    railway_section: str | None = None
    time_range: str | None = None
    data_version: str | None = None
    metric_name: str | None = None
    exception_description: str | None = None


class BusinessUnderstandingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(min_length=1)
    route: BusinessRoute
    intent: BusinessIntent | None = None
    entities: BusinessEntities = Field(default_factory=BusinessEntities)
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_route_contract(self) -> Self:
        if self.route is BusinessRoute.BUSINESS:
            if self.intent is None or self.clarification_question is not None:
                raise ValueError("BUSINESS requires intent and forbids clarification")
        elif self.route is BusinessRoute.NON_BUSINESS:
            if self.intent is not None or self.clarification_question is not None:
                raise ValueError("NON_BUSINESS forbids intent and clarification")
        elif not (self.clarification_question and self.clarification_question.strip()):
            raise ValueError("CLARIFY requires a non-blank question")
        return self


class ClarificationInterruptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["business_clarification"] = "business_clarification"
    question: str = Field(min_length=1, pattern=r"\S")

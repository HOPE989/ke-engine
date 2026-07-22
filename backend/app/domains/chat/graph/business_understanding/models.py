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

    operation_plan_no: str | None = Field(
        default=None,
        description="铁路运输运行计划的唯一编号，仅在消息明确提供计划编号时填写。",
    )
    train_no: str | None = Field(
        default=None,
        description="列车车次或列车编号，仅在消息明确提供车次时填写。",
    )
    formation_no: str | None = Field(
        default=None,
        description="铁路车辆编组的唯一编号，仅在消息明确提供编组编号时填写。",
    )
    contract_no: str | None = Field(
        default=None,
        description="煤炭销售或运输合同的唯一编号，仅在消息明确提供合同号时填写。",
    )
    document_type: str | None = Field(
        default=None,
        description="业务单据类型，例如运单或货票；不得另建 term、topic 等字段。",
    )
    document_no: str | None = Field(
        default=None,
        description="运单、货票等业务单据的唯一编号。",
    )
    customer: str | None = Field(
        default=None,
        description="业务请求中明确提及的客户名称。",
    )
    supplier: str | None = Field(
        default=None,
        description="业务请求中明确提及的供应商名称。",
    )
    coal_type: str | None = Field(
        default=None,
        description="业务请求中明确提及的煤种或煤炭品类。",
    )
    departure_station: str | None = Field(
        default=None,
        description="铁路运输的发站或出发车站，例如神木站、榆林站。",
    )
    arrival_station: str | None = Field(
        default=None,
        description="铁路运输的到站或目的车站。",
    )
    railway_section: str | None = Field(
        default=None,
        description="业务请求中明确提及的铁路区段或运输区间。",
    )
    time_range: str | None = Field(
        default=None,
        description="查询的时间范围或日期表达，例如昨日、本月；不得另建 time、date 字段。",
    )
    data_version: str | None = Field(
        default=None,
        description="业务数据版本，仅填写实际版或模拟版等消息中明确指定的版本。",
    )
    metric_name: str | None = Field(
        default=None,
        description=(
            "查询或讨论的业务指标、计划或专业指标名称，例如装车数量、装车计划、"
            "运行计划、编组计划、发热量。"
        ),
    )
    exception_description: str | None = Field(
        default=None,
        description="业务请求中明确描述的异常事项，例如合同履约异常。",
    )


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

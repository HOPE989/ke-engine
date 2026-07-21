from langchain_core.messages import AIMessage

from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult


class FakeStructuredRunnable:
    def __init__(self, results: list[BusinessUnderstandingResult]):
        self.results = list(results)
        self.calls: list[list[object]] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.results.pop(0)


class FakeSequentialChatModel:
    """贴合 structured runnable 与普通 chat model 的测试替身。"""

    def __init__(
        self,
        structured_results: list[BusinessUnderstandingResult],
        ordinary_response: AIMessage | None = None,
    ):
        self.structured_runnable = FakeStructuredRunnable(structured_results)
        self.ordinary_response = ordinary_response
        self.structured_schemas: list[type[BusinessUnderstandingResult]] = []
        self.ordinary_calls: list[list[object]] = []

    def with_structured_output(self, schema):
        self.structured_schemas.append(schema)
        return self.structured_runnable

    async def ainvoke(self, messages):
        self.ordinary_calls.append(messages)
        if self.ordinary_response is None:
            raise AssertionError("route must not invoke the ordinary model")
        return self.ordinary_response

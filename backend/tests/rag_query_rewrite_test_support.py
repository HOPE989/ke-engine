from collections.abc import Iterable


class RecordingStructuredRunnable:
    def __init__(self, results: Iterable[object] = (), *, error=None):
        self.results = list(results)
        self.error = error
        self.calls = []

    async def ainvoke(self, messages, config=None):
        self.calls.append((messages, config))
        if self.error is not None:
            raise self.error
        if not self.results:
            raise AssertionError("no structured result configured")
        return self.results.pop(0)


class RecordingStructuredModel:
    def __init__(self, runnable, *, binding_error=None):
        self.runnable = runnable
        self.binding_error = binding_error
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        if self.binding_error is not None:
            raise self.binding_error
        return self.runnable

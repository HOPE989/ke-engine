from collections.abc import Iterable

from langchain_core.documents import Document


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
        self.structured_output_calls = []

    def with_structured_output(self, schema, **kwargs):
        self.schemas.append(schema)
        self.structured_output_calls.append(
            {"schema": schema, **kwargs}
        )
        if self.binding_error is not None:
            raise self.binding_error
        return self.runnable


class RecordingRetriever:
    def __init__(self, documents=(), *, error=None):
        self.documents = list(documents)
        self.error = error
        self.calls = []

    async def ainvoke(self, query, config=None):
        self.calls.append((query, config))
        if self.error is not None:
            raise self.error
        return list(self.documents)


class RecordingRetrieverFactory:
    def __init__(self, documents=(), *, error=None):
        self.documents = list(documents)
        self.error = error
        self.scopes = []
        self.retrievers = []

    def create(self, scope):
        self.scopes.append(scope)
        retriever = RecordingRetriever(
            self.documents,
            error=self.error,
        )
        self.retrievers.append(retriever)
        return retriever


def document(
    *,
    text="合同付款周期为三十天。",
    chunk_id="chunk-1",
    doc_id="doc-1",
    **metadata,
):
    return Document(
        page_content=text,
        metadata={
            "chunkId": chunk_id,
            "docId": doc_id,
            **metadata,
        },
    )

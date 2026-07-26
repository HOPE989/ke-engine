from types import SimpleNamespace

import pytest
from langfuse.api.commons.errors import NotFoundError

from app.domains.rag.graph.query_router import (
    QueryRouteResult,
    RetrieverKind,
)
from app.domains.rag.graph.query_router.evaluation import (
    load_query_router_evaluation_cases,
)
from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


def test_router_dataset_mapping_is_stable_and_preserves_expected_set():
    from app.evaluation.rag_query_router import (
        dataset_item_id,
        dataset_item_payload,
    )

    case = load_query_router_evaluation_cases()[0]

    first = dataset_item_payload(case)
    second = dataset_item_payload(case)

    assert first == second
    assert first["id"] == dataset_item_id(case)
    assert first["input"] == case.request.model_dump(mode="json")
    assert first["expected_output"] == {
        "selected_retrievers": [
            retriever.value for retriever in case.expected_retrievers
        ]
    }
    assert first["metadata"] == {
        "case_id": case.id,
        "category": case.category,
    }


def test_router_langfuse_evaluator_reports_objective_set_metrics():
    from app.evaluation.rag_query_router import langfuse_evaluator

    evaluations = langfuse_evaluator(
        output={
            "retrieval_plan": {
                "selected_retrievers": [
                    "DOCUMENT_HYBRID",
                    "SQL",
                    "GRAPH",
                ],
                "routing_reason": "选择过多",
                "decision_source": "MODEL",
            }
        },
        expected_output={
            "selected_retrievers": ["DOCUMENT_HYBRID", "SQL"]
        },
    )

    assert [evaluation.name for evaluation in evaluations] == [
        "route_output_contract",
        "route_set_exact",
        "over_route_count",
        "under_route_count",
    ]
    assert [float(evaluation.value) for evaluation in evaluations] == [
        1.0,
        0.0,
        1.0,
        0.0,
    ]


@pytest.mark.asyncio
async def test_router_experiment_task_invokes_production_router_node():
    from app.evaluation.rag_query_router import run_query_router_case

    case = next(
        case
        for case in load_query_router_evaluation_cases()
        if case.id == "document-sql"
    )
    runnable = RecordingStructuredRunnable(
        [
            QueryRouteResult(
                selected_retrievers=[
                    RetrieverKind.SQL,
                    RetrieverKind.DOCUMENT_HYBRID,
                ],
                routing_reason="需要统计数据和统计口径",
            ),
        ]
    )
    item = SimpleNamespace(input=case.request.model_dump(mode="json"))

    output = await run_query_router_case(
        item=item,
        model=RecordingStructuredModel(runnable),
    )

    assert output["retrieval_plan"]["selected_retrievers"] == [
        "DOCUMENT_HYBRID",
        "SQL",
    ]
    assert len(runnable.calls) == 1


class FakeExperimentResult:
    dataset_run_url = "http://langfuse.local/project/datasets/router-run-1"

    def format(self):
        return "10 items evaluated"


class FakeDataset:
    def __init__(self):
        self.experiment_calls = []
        self.result = FakeExperimentResult()

    def run_experiment(self, **kwargs):
        self.experiment_calls.append(kwargs)
        return self.result


class FakeLangfuseClient:
    def __init__(self, *, dataset_exists=True):
        self.dataset_exists = dataset_exists
        self.dataset = FakeDataset()
        self.created_datasets = []
        self.created_items = []
        self.shutdown_calls = 0

    def get_dataset(self, name):
        assert name == "ke-engine/rag-query-router-v1"
        if not self.dataset_exists:
            raise NotFoundError({"message": "not found"})
        return self.dataset

    def create_dataset(self, **kwargs):
        self.created_datasets.append(kwargs)
        self.dataset_exists = True

    def create_dataset_item(self, **kwargs):
        self.created_items.append(kwargs)

    def auth_check(self):
        return True

    def shutdown(self):
        self.shutdown_calls += 1


def test_router_sync_dataset_creates_and_upserts_all_items():
    from app.evaluation.rag_query_router import (
        DATASET_NAME,
        sync_dataset,
    )

    client = FakeLangfuseClient(dataset_exists=False)

    dataset = sync_dataset(
        client,
        load_query_router_evaluation_cases(),
    )

    assert dataset is client.dataset
    assert client.created_datasets == [
        {
            "name": DATASET_NAME,
            "description": "10 labeled RAG Query Router route-set cases",
            "metadata": {
                "source": "ke-engine",
                "route_scoring": "objective-set-match",
            },
        }
    ]
    assert len(client.created_items) == 10
    assert all(
        item["dataset_name"] == DATASET_NAME
        for item in client.created_items
    )


def test_router_run_experiment_is_explicit_and_serial(monkeypatch, capsys):
    from app.evaluation import rag_query_router as module

    client = FakeLangfuseClient()
    resources = SimpleNamespace(client=client, handler=object())
    assembled_model = object()
    monkeypatch.setattr(
        module,
        "create_chat_model",
        lambda settings, *, model, callbacks: assembled_model,
    )
    settings = SimpleNamespace(
        openai_model="deepseek-test",
        app_version="0.1.0",
    )

    result = module.run_experiment(settings, resources=resources)

    assert result is client.dataset.result
    assert len(client.created_items) == 10
    call = client.dataset.experiment_calls[0]
    assert call["max_concurrency"] == 1
    assert call["evaluators"] == [module.langfuse_evaluator]
    assert call["task"].keywords == {"model": assembled_model}
    assert call["metadata"] == {
        "model": "deepseek-test",
        "query_router_prompt_version": "v1",
        "query_rewrite_prompt_version": "v2",
        "app_version": "0.1.0",
        "live_model": "true",
        "route_scoring": "objective-set-match",
    }
    assert client.shutdown_calls == 1
    stdout = capsys.readouterr().out
    assert "10 items evaluated" in stdout
    assert client.dataset.result.dataset_run_url in stdout


def test_router_main_returns_nonzero_without_implicit_fallback(
    monkeypatch,
    capsys,
):
    from app.evaluation import rag_query_router as module

    monkeypatch.setattr(
        module,
        "run_experiment",
        lambda settings: (_ for _ in ()).throw(
            RuntimeError("Langfuse configuration is required")
        ),
    )

    assert module.main() == 1
    assert "Langfuse experiment failed" in capsys.readouterr().err

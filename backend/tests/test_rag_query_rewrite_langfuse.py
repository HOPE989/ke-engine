from types import SimpleNamespace

import pytest
from langfuse.api.commons.errors import NotFoundError

from app.domains.rag.graph.query_rewrite import QueryRewriteResult
from app.domains.rag.graph.query_rewrite.evaluation import (
    load_query_rewrite_evaluation_cases,
)
from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


def test_dataset_mapping_is_stable_and_preserves_human_review_fields():
    from app.evaluation.rag_query_rewrite import (
        dataset_item_id,
        dataset_item_payload,
    )

    case = load_query_rewrite_evaluation_cases()[0]

    first = dataset_item_payload(case)
    second = dataset_item_payload(case)

    assert first == second
    assert first["id"] == dataset_item_id(case)
    assert first["input"] == case.request.model_dump(mode="json")
    assert first["expected_output"] == {
        "expected_standalone_query": case.expected_standalone_query,
        "semantic_review": {
            "preserved_terms": list(case.expected_preserved_terms),
            "required_term_groups": [
                list(group)
                for group in case.expected_required_term_groups
            ],
            "excluded_terms": list(case.expected_excluded_terms),
        },
    }
    assert first["metadata"] == {
        "case_id": case.id,
        "category": case.category,
    }


def test_all_dataset_item_ids_are_unique_and_project_stable():
    from app.evaluation.rag_query_rewrite import dataset_item_id

    ids = [
        dataset_item_id(case)
        for case in load_query_rewrite_evaluation_cases()
    ]

    assert len(ids) == len(set(ids)) == 28


def test_langfuse_evaluator_only_reports_objective_output_contract():
    from app.evaluation.rag_query_rewrite import langfuse_evaluator

    evaluations = langfuse_evaluator(
        input={"original_query": "查询运单"},
        output={"standalone_query": "与人工参考不同但契约有效的查询"},
        expected_output={
            "expected_standalone_query": "查询运单YD2026001",
            "semantic_review": {
                "preserved_terms": ["YD2026001"],
                "required_term_groups": [],
                "excluded_terms": [],
            },
        },
        metadata={},
    )

    assert len(evaluations) == 1
    assert evaluations[0].name == "output_contract"
    assert float(evaluations[0].value) == 1.0
    assert evaluations[0].data_type == "NUMERIC"
    assert evaluations[0].comment == "1/1"


@pytest.mark.asyncio
async def test_experiment_task_invokes_compiled_production_rag_graph():
    from app.domains.rag.graph import build_rag_graph
    from app.evaluation.rag_query_rewrite import run_query_rewrite_case

    case = load_query_rewrite_evaluation_cases()[0]
    runnable = RecordingStructuredRunnable(
        [QueryRewriteResult(standalone_query="查询神木站实际版装车计划")]
    )
    graph = build_rag_graph(
        model=RecordingStructuredModel(runnable)
    ).compile()
    item = SimpleNamespace(
        input=case.request.model_dump(mode="json")
    )

    output = await run_query_rewrite_case(item=item, graph=graph)

    assert output == {
        "standalone_query": "查询神木站实际版装车计划"
    }
    assert len(runnable.calls) == 1


class FakeExperimentResult:
    dataset_run_url = "http://langfuse.local/project/datasets/run-rag-1"

    def format(self):
        return "28 items evaluated"


class FakeDataset:
    def __init__(self):
        self.experiment_calls = []
        self.result = FakeExperimentResult()

    def run_experiment(self, **kwargs):
        self.experiment_calls.append(kwargs)
        return self.result


class FakeLangfuseClient:
    def __init__(self, *, dataset_exists=True, auth_valid=True):
        self.dataset_exists = dataset_exists
        self.auth_valid = auth_valid
        self.dataset = FakeDataset()
        self.created_datasets = []
        self.created_items = []
        self.shutdown_calls = 0

    def get_dataset(self, name):
        assert name == "ke-engine/rag-query-rewrite-v1"
        if not self.dataset_exists:
            raise NotFoundError({"message": "not found"})
        return self.dataset

    def create_dataset(self, **kwargs):
        self.created_datasets.append(kwargs)
        self.dataset_exists = True

    def create_dataset_item(self, **kwargs):
        self.created_items.append(kwargs)

    def auth_check(self):
        return self.auth_valid

    def shutdown(self):
        self.shutdown_calls += 1


def test_sync_dataset_creates_then_upserts_all_28_items():
    from app.evaluation.rag_query_rewrite import (
        DATASET_NAME,
        sync_dataset,
    )

    client = FakeLangfuseClient(dataset_exists=False)

    dataset = sync_dataset(
        client,
        load_query_rewrite_evaluation_cases(),
    )

    assert dataset is client.dataset
    assert client.created_datasets == [
        {
            "name": DATASET_NAME,
            "description": (
                "28 labeled RAG Query Rewrite semantic review cases"
            ),
            "metadata": {
                "source": "ke-engine",
                "semantic_scoring": "human-or-calibrated-llm-judge",
            },
        }
    ]
    assert len(client.created_items) == 28
    assert all(
        item["dataset_name"] == DATASET_NAME
        for item in client.created_items
    )


def test_run_experiment_syncs_dataset_and_runs_serial_production_graph(
    monkeypatch,
    capsys,
):
    from app.evaluation import rag_query_rewrite as module

    client = FakeLangfuseClient()
    handler = object()
    resources = SimpleNamespace(client=client, handler=handler)
    model = object()
    compiled_graph = object()
    graph_builder = SimpleNamespace(
        compile=lambda: compiled_graph
    )
    monkeypatch.setattr(
        module,
        "create_chat_model",
        lambda settings, *, model, callbacks: model,
    )
    monkeypatch.setattr(
        module,
        "build_rag_graph",
        lambda *, model: graph_builder,
    )
    settings = SimpleNamespace(
        openai_model="deepseek-test",
        app_version="0.1.0",
    )

    result = module.run_experiment(settings, resources=resources)

    assert result is client.dataset.result
    assert len(client.created_items) == 28
    call = client.dataset.experiment_calls[0]
    assert call["max_concurrency"] == 1
    assert call["evaluators"] == [module.langfuse_evaluator]
    assert call["task"].keywords == {"graph": compiled_graph}
    assert call["metadata"] == {
        "model": "deepseek-test",
        "prompt_version": "v2",
        "app_version": "0.1.0",
        "live_model": "true",
        "semantic_scoring": "not_automated",
    }
    assert client.shutdown_calls == 1
    stdout = capsys.readouterr().out
    assert "28 items evaluated" in stdout
    assert client.dataset.result.dataset_run_url in stdout


def test_main_returns_nonzero_without_running_implicit_fallback(
    monkeypatch,
    capsys,
):
    from app.evaluation import rag_query_rewrite as module

    monkeypatch.setattr(
        module,
        "run_experiment",
        lambda settings: (_ for _ in ()).throw(
            RuntimeError("Langfuse configuration is required")
        ),
    )

    assert module.main() == 1
    assert "Langfuse experiment failed" in capsys.readouterr().err

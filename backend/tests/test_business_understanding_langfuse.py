from types import SimpleNamespace

import pytest

from app.domains.chat.graph.business_understanding import (
    BusinessIntent,
    BusinessRoute,
    BusinessUnderstandingResult,
)
from app.domains.chat.graph.business_understanding.evaluation import (
    load_evaluation_cases,
)
from app.domains.chat.graph.business_understanding.prompt import (
    BUSINESS_UNDERSTANDING_PROMPT_VERSION,
    build_business_understanding_messages,
)
from chat_graph_test_support import FakeSequentialChatModel
from langfuse.api.commons.errors import NotFoundError


def _oracle_output(case):
    return {
        "reasoning": "fixture oracle",
        "route": case.expected_route.value,
        "intent": (
            case.expected_intent.value if case.expected_intent is not None else None
        ),
        "entities": case.expected_key_entities,
        "clarification_question": case.expected_clarification_contains,
    }


def test_dataset_mapping_is_stable_and_preserves_all_case_fields():
    from app.evaluation.business_understanding_langfuse import (
        dataset_item_id,
        dataset_item_payload,
    )

    case = load_evaluation_cases()[0]

    first = dataset_item_payload(case)
    second = dataset_item_payload(case)

    assert first == second
    assert first["id"] == dataset_item_id(case)
    assert first["input"] == {"messages": case.messages}
    assert first["expected_output"] == {
        "route": case.expected_route.value,
        "intent": None,
        "key_entities": {},
        "clarification_contains": None,
    }
    assert first["metadata"] == {
        "case_id": case.id,
        "category": case.category,
    }


def test_all_cases_have_unique_project_level_item_ids():
    from app.evaluation.business_understanding_langfuse import dataset_item_id

    ids = [dataset_item_id(case) for case in load_evaluation_cases()]

    assert len(ids) == len(set(ids)) == 26


def test_langfuse_evaluator_returns_five_numeric_scores_from_existing_scorer():
    from app.evaluation.business_understanding_langfuse import (
        dataset_item_payload,
        langfuse_evaluator,
    )

    case = load_evaluation_cases()[2]
    payload = dataset_item_payload(case)

    evaluations = langfuse_evaluator(
        input=payload["input"],
        output=_oracle_output(case),
        expected_output=payload["expected_output"],
        metadata={},
    )

    assert {evaluation.name for evaluation in evaluations} == {
        "route_accuracy",
        "intent_accuracy",
        "key_entity_recall",
        "clarification_accuracy",
        "schema_validity",
    }
    assert all(evaluation.data_type == "NUMERIC" for evaluation in evaluations)
    assert all(float(evaluation.value) == 1.0 for evaluation in evaluations)
    assert all(evaluation.comment and "/" in evaluation.comment for evaluation in evaluations)


@pytest.mark.asyncio
async def test_experiment_task_invokes_real_node_with_complete_message_history():
    from app.evaluation.business_understanding_langfuse import (
        langchain_messages,
        run_business_understanding_case,
    )

    case = next(
        case for case in load_evaluation_cases() if case.id == "actual-followup"
    )
    result = BusinessUnderstandingResult(
        reasoning="继承历史中的站点和指标",
        route=BusinessRoute.BUSINESS,
        intent=BusinessIntent.BUSINESS_DATA_QUERY,
        entities={
            "departure_station": "神木站",
            "time_range": "本月",
            "data_version": "实际版",
            "metric_name": "装车计划",
        },
    )
    model = FakeSequentialChatModel([result])
    item = SimpleNamespace(input={"messages": case.messages})

    output = await run_business_understanding_case(item=item, model=model)

    expected_messages = langchain_messages(case.messages)
    assert output == result.model_dump(mode="json")
    assert model.structured_runnable.calls == [
        build_business_understanding_messages(expected_messages)
    ]


class FakeExperimentResult:
    dataset_run_url = "http://langfuse.local/project/datasets/run-1"

    def format(self):
        return "26 items evaluated"


class FakeDataset:
    def __init__(self, *, result=None, experiment_error=None):
        self.result = result or FakeExperimentResult()
        self.experiment_error = experiment_error
        self.experiment_calls = []

    def run_experiment(self, **kwargs):
        self.experiment_calls.append(kwargs)
        if self.experiment_error is not None:
            raise self.experiment_error
        return self.result


class FakeLangfuseClient:
    def __init__(
        self,
        *,
        dataset_exists=True,
        auth_valid=True,
        result=None,
        experiment_error=None,
    ):
        self.dataset_exists = dataset_exists
        self.auth_valid = auth_valid
        self.dataset = FakeDataset(result=result, experiment_error=experiment_error)
        self.created_datasets = []
        self.created_items = []
        self.get_dataset_calls = []
        self.shutdown_calls = 0

    def get_dataset(self, name):
        self.get_dataset_calls.append(name)
        assert name == "ke-engine/business-understanding-v1"
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


def _experiment_settings():
    return SimpleNamespace(
        openai_model="gpt-test",
        app_version="0.1.0",
    )


def test_sync_dataset_creates_then_upserts_all_items():
    from app.evaluation.business_understanding_langfuse import (
        DATASET_NAME,
        sync_dataset,
    )

    client = FakeLangfuseClient(dataset_exists=False)

    dataset = sync_dataset(client, load_evaluation_cases())

    assert dataset is client.dataset
    assert client.created_datasets[0]["name"] == DATASET_NAME
    assert len(client.created_items) == 26
    assert all(item["dataset_name"] == DATASET_NAME for item in client.created_items)
    assert len({item["id"] for item in client.created_items}) == 26


def test_sync_dataset_reuses_existing_dataset_and_still_upserts_items():
    from app.evaluation.business_understanding_langfuse import sync_dataset

    client = FakeLangfuseClient(dataset_exists=True)

    sync_dataset(client, load_evaluation_cases())

    assert client.created_datasets == []
    assert len(client.created_items) == 26


def test_run_experiment_is_serial_traced_and_prints_dataset_run_url(
    monkeypatch,
    capsys,
):
    from app.evaluation import business_understanding_langfuse as module

    client = FakeLangfuseClient()
    handler = object()
    resources = SimpleNamespace(client=client, handler=handler)
    model_instance = object()
    model_calls = []
    monkeypatch.setattr(
        module,
        "create_chat_model",
        lambda settings, *, model, callbacks: model_calls.append(
            {"settings": settings, "model": model, "callbacks": callbacks}
        )
        or model_instance,
    )
    settings = _experiment_settings()

    result = module.run_experiment(settings, resources=resources)

    assert result is client.dataset.result
    assert client.get_dataset_calls == [module.DATASET_NAME]
    assert client.created_items == []
    assert model_calls == [
        {"settings": settings, "model": "gpt-test", "callbacks": [handler]}
    ]
    call = client.dataset.experiment_calls[0]
    assert call["max_concurrency"] == 1
    assert call["evaluators"] == [module.langfuse_evaluator]
    assert call["metadata"] == {
        "model": "gpt-test",
        "prompt_version": "v2",
        "app_version": "0.1.0",
        "live_model": "true",
    }
    assert call["task"].keywords == {"model": model_instance}
    output = capsys.readouterr().out
    assert "26 items evaluated" in output
    assert FakeExperimentResult.dataset_run_url in output
    assert client.shutdown_calls == 1


def test_explicit_upsert_command_writes_cases_without_running_experiment(capsys):
    from app.evaluation.upsert_business_understanding_dataset import upsert_dataset

    client = FakeLangfuseClient()
    resources = SimpleNamespace(client=client, handler=object())

    dataset = upsert_dataset(_experiment_settings(), resources=resources)

    assert dataset is client.dataset
    assert len(client.created_items) == 26
    assert client.dataset.experiment_calls == []
    assert client.shutdown_calls == 1
    assert "Upserted 26 items" in capsys.readouterr().out


@pytest.mark.parametrize(
    "client",
    [
        FakeLangfuseClient(auth_valid=False),
        FakeLangfuseClient(experiment_error=RuntimeError("remote failed")),
    ],
)
def test_run_experiment_fails_fast_and_always_shuts_down(client):
    from app.evaluation.business_understanding_langfuse import run_experiment

    resources = SimpleNamespace(client=client, handler=object())

    with pytest.raises(RuntimeError):
        run_experiment(_experiment_settings(), resources=resources)

    assert client.shutdown_calls == 1


def test_main_returns_nonzero_when_langfuse_configuration_is_missing(
    monkeypatch,
    capsys,
):
    from app.evaluation import business_understanding_langfuse as module

    monkeypatch.setattr(module, "create_settings", _experiment_settings)
    monkeypatch.setattr(module, "create_langfuse_resources", lambda settings: None)

    assert module.main() == 1
    assert "Langfuse configuration is required" in capsys.readouterr().err

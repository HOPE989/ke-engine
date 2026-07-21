from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.types import Command, Interrupt, PregelTask, StateSnapshot
import pytest

from app.domains.chat.graph.routing import CLARIFY_NODE, LLM_NODE
from app.domains.chat.services.conversation import AcceptedUserTurn


CONFIG = {"configurable": {"thread_id": "1001"}}


def make_task(
    *,
    name: str = CLARIFY_NODE,
    interrupts: tuple[Interrupt, ...] | None = None,
    task_id: str = "task-1",
) -> PregelTask:
    if interrupts is None:
        interrupts = (
            Interrupt(
                value={
                    "kind": "business_clarification",
                    "question": "请提供运单号",
                },
                id="internal-interrupt-id",
            ),
        )
    return PregelTask(
        id=task_id,
        name=name,
        path=("__pregel_pull", name),
        interrupts=interrupts,
    )


def make_snapshot(
    *,
    next_nodes: tuple[str, ...] = (),
    tasks: tuple[PregelTask, ...] = (),
) -> StateSnapshot:
    return StateSnapshot(
        values={},
        next=next_nodes,
        config=CONFIG,
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=tasks,
        interrupts=tuple(
            interrupt for task in tasks for interrupt in task.interrupts
        ),
    )


class FakeGraph:
    def __init__(self, snapshot: StateSnapshot, calls: list[str]) -> None:
        self.snapshot = snapshot
        self.calls = calls
        self.state_configs: list[dict[str, object]] = []
        self.stream_invocations: list[dict[str, object]] = []

    async def aget_state(self, config):
        self.calls.append("aget_state")
        self.state_configs.append(config)
        return self.snapshot

    async def astream_events(self, graph_input, config, *, context, version):
        self.calls.append("astream_events")
        self.stream_invocations.append(
            {
                "input": graph_input,
                "config": config,
                "context": context,
                "version": version,
            }
        )
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": AIMessageChunk(content="业务结果")},
            "metadata": {"langgraph_node": LLM_NODE},
        }


class FakePublisher:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.events = []

    async def publish(self, event, payload):
        self.calls.append(f"publish_{event}")
        self.events.append((event, payload))


class FakeTransaction:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.session.calls.append("assistant_commit")


class FakeSession:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return FakeTransaction(self)

    def add(self, value):
        self.added.append(value)


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self):
        return self.session


class FakeIdGenerator:
    def next_id(self):
        return 3001


def make_producer(snapshot: StateSnapshot):
    from app.domains.chat.services.runtime import CompletionProducer

    calls: list[str] = []
    publisher = FakePublisher(calls)
    graph = FakeGraph(snapshot, calls)
    session = FakeSession(calls)
    producer = CompletionProducer(
        graph=graph,
        model=object(),
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(),
        publisher=publisher,
    )
    return producer, graph, publisher, session, calls


@pytest.mark.asyncio
async def test_no_pending_checkpoint_starts_normal_human_message_turn():
    producer, graph, publisher, session, calls = make_producer(make_snapshot())

    await producer.run(
        turn=AcceptedUserTurn(1001, 2001, "hello"),
        user_id="alice",
    )

    invocation = graph.stream_invocations[0]
    assert invocation["input"] == {"messages": [HumanMessage(content="hello")]}
    assert graph.state_configs == [CONFIG]
    assert invocation["config"] == CONFIG
    assert graph.state_configs[0] is invocation["config"]
    assert calls.index("publish_metadata") < calls.index("aget_state")
    assert calls.index("aget_state") < calls.index("astream_events")
    assert session.added[0].content == "业务结果"
    assert publisher.events[-1][0] == "completed"


@pytest.mark.asyncio
async def test_pending_clarification_resumes_with_content_on_same_thread():
    snapshot = make_snapshot(
        next_nodes=(CLARIFY_NODE,),
        tasks=(make_task(),),
    )
    producer, graph, publisher, session, calls = make_producer(snapshot)

    await producer.run(
        turn=AcceptedUserTurn(1001, 2001, "YD2026001"),
        user_id="alice",
    )

    invocation = graph.stream_invocations[0]
    graph_input = invocation["input"]
    assert isinstance(graph_input, Command)
    assert graph_input.resume == "YD2026001"
    assert graph.state_configs == [CONFIG]
    assert invocation["config"] == CONFIG
    assert graph.state_configs[0] is invocation["config"]
    assert calls.index("aget_state") < calls.index("astream_events")
    assert session.added[0].content == "业务结果"
    assert publisher.events[-1][0] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot",
    [
        make_snapshot(
            next_nodes=(CLARIFY_NODE,),
            tasks=(make_task(name="unknown"),),
        ),
        make_snapshot(
            next_nodes=(CLARIFY_NODE,),
            tasks=(make_task(), make_task(task_id="task-2")),
        ),
        make_snapshot(
            next_nodes=(CLARIFY_NODE,),
            tasks=(make_task(interrupts=()),),
        ),
        make_snapshot(
            next_nodes=(CLARIFY_NODE,),
            tasks=(
                make_task(
                    interrupts=(
                        Interrupt(
                            value={
                                "kind": "business_clarification",
                                "question": "问题一",
                            },
                            id="interrupt-1",
                        ),
                        Interrupt(
                            value={
                                "kind": "business_clarification",
                                "question": "问题二",
                            },
                            id="interrupt-2",
                        ),
                    )
                ),
            ),
        ),
        make_snapshot(
            next_nodes=(CLARIFY_NODE,),
            tasks=(
                make_task(
                    interrupts=(
                        Interrupt(
                            value={
                                "kind": "business_clarification",
                                "question": "   ",
                            },
                            id="blank-question",
                        ),
                    )
                ),
            ),
        ),
        make_snapshot(
            next_nodes=(CLARIFY_NODE,),
            tasks=(
                make_task(
                    interrupts=(
                        Interrupt(
                            value={"kind": "unknown", "question": "raw-secret"},
                            id="malformed-payload",
                        ),
                    )
                ),
            ),
        ),
    ],
    ids=[
        "unknown-task",
        "multiple-tasks",
        "no-interrupt",
        "multiple-interrupts",
        "blank-question",
        "malformed-payload",
    ],
)
async def test_unsupported_pending_checkpoint_fails_without_starting_new_turn(snapshot):
    producer, graph, publisher, session, calls = make_producer(snapshot)

    await producer.run(
        turn=AcceptedUserTurn(1001, 2001, "YD2026001"),
        user_id="alice",
    )

    assert [event for event, _ in publisher.events] == ["metadata", "error"]
    assert graph.state_configs == [CONFIG]
    assert graph.stream_invocations == []
    assert "astream_events" not in calls
    assert session.added == []
    assert "raw-secret" not in publisher.events[-1][1].model_dump_json()

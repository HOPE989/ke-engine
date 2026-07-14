import json

from langchain_core.messages import AIMessageChunk

from app.contracts.chat.stream import (
    CompletedPayload,
    ContentDeltaPayload,
    ErrorPayload,
    MetadataPayload,
)


def _decode_frame(frame):
    lines = frame.decode().splitlines()
    return lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))


def test_encode_sse_uses_valid_event_and_json_data_frames():
    from app.services.chat_api.streaming import encode_sse

    frames = [
        encode_sse("metadata", MetadataPayload(conversation_id=1, user_message_id=2)),
        encode_sse("content_delta", ContentDeltaPayload(content="你\n好")),
        encode_sse("completed", CompletedPayload(assistant_message_id=3)),
        encode_sse(
            "error",
            ErrorPayload(code="MODEL_FAILED", message="模型调用失败", retryable=True),
        ),
    ]

    assert all(frame.endswith(b"\n\n") for frame in frames)
    assert [_decode_frame(frame) for frame in frames] == [
        ("metadata", {"conversation_id": "1", "user_message_id": "2"}),
        ("content_delta", {"content": "你\n好"}),
        ("completed", {"assistant_message_id": "3", "finish_reason": "stop"}),
        (
            "error",
            {"code": "MODEL_FAILED", "message": "模型调用失败", "retryable": True},
        ),
    ]


def test_project_graph_events_preserves_text_chunk_order_without_internal_fields():
    from app.services.chat_api.streaming import project_graph_event

    events = [
        {
            "event": "on_chat_model_stream",
            "name": "fake-model",
            "run_id": "run-1",
            "tags": ["internal"],
            "metadata": {"checkpoint_ns": "secret"},
            "data": {"chunk": AIMessageChunk(content="你")},
        },
        {
            "event": "on_chat_model_stream",
            "name": "fake-model",
            "run_id": "run-1",
            "data": {"chunk": AIMessageChunk(content="好")},
        },
    ]

    payloads = [project_graph_event(event) for event in events]

    assert [payload.content for payload in payloads] == ["你", "好"]
    assert [payload.model_dump() for payload in payloads] == [
        {"content": "你"},
        {"content": "好"},
    ]


def test_project_graph_event_ignores_empty_and_non_public_events():
    from app.services.chat_api.streaming import project_graph_event

    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="")}},
        {"event": "on_chain_start", "data": {"input": "internal"}},
        {"event": "on_chat_model_end", "data": {"output": "internal"}},
        {"event": "on_chat_model_stream", "data": {"chunk": object()}},
    ]

    assert [project_graph_event(event) for event in events] == [None, None, None, None]

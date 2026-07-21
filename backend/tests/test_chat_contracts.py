from datetime import UTC, datetime
from inspect import getsource
from typing import get_args

import pytest
from pydantic import ValidationError

import app.contracts.chat
from app.contracts.chat import CompletionFinishReason
from app.contracts.chat.http import (
    CompletionRequest,
    ConversationPage,
    ConversationSummary,
    MessagePage,
    MessageSummary,
)
from app.contracts.chat.stream import (
    CompletedPayload,
    ContentDeltaPayload,
    ErrorPayload,
    MetadataPayload,
)


@pytest.mark.parametrize("content", ["", " ", "\t\r\n"])
def test_completion_request_rejects_blank_content(content):
    with pytest.raises(ValidationError):
        CompletionRequest(content=content)


@pytest.mark.parametrize(
    "conversation_id",
    [123, "-1", "+1", "1.0", " 123", "123 ", "abc", ""],
)
def test_completion_request_accepts_only_decimal_string_conversation_ids(
    conversation_id,
):
    with pytest.raises(ValidationError):
        CompletionRequest(conversation_id=conversation_id, content="hello")

    request = CompletionRequest(conversation_id="2036854775807", content="hello")

    assert request.conversation_id == "2036854775807"


def test_completion_request_does_not_allow_client_model_selection():
    with pytest.raises(ValidationError):
        CompletionRequest(content="hello", model="client-selected-model")

    assert "model" not in CompletionRequest.model_fields


def test_chat_http_response_identifiers_serialize_as_strings():
    timestamp = datetime(2026, 7, 14, tzinfo=UTC)
    conversation = ConversationSummary(
        id=2036854775807,
        title="hello",
        status="ACTIVE",
        created_at=timestamp,
        updated_at=timestamp,
    )
    message = MessageSummary(
        id=2036854775808,
        conversation_id=2036854775807,
        parent_message_id=2036854775806,
        role="ASSISTANT",
        content="world",
        created_at=timestamp,
    )

    conversation_page = ConversationPage(items=[conversation], next_cursor="next")
    message_page = MessagePage(items=[message], next_cursor=None)

    assert conversation_page.model_dump(mode="json")["items"][0]["id"] == "2036854775807"
    assert message_page.model_dump(mode="json")["items"][0] == {
        "id": "2036854775808",
        "conversation_id": "2036854775807",
        "parent_message_id": "2036854775806",
        "role": "ASSISTANT",
        "content": "world",
        "created_at": "2026-07-14T00:00:00Z",
    }


def test_chat_sse_payloads_have_fixed_public_fields_and_string_ids():
    payloads = [
        MetadataPayload(conversation_id=2036854775807, user_message_id=2036854775808),
        ContentDeltaPayload(content="你"),
        CompletedPayload(assistant_message_id=2036854775809, finish_reason="stop"),
        ErrorPayload(code="MODEL_INVOCATION_FAILED", message="模型调用失败", retryable=True),
    ]

    assert [set(type(payload).model_fields) for payload in payloads] == [
        {"conversation_id", "user_message_id"},
        {"content"},
        {"assistant_message_id", "finish_reason"},
        {"code", "message", "retryable"},
    ]
    assert payloads[0].model_dump(mode="json") == {
        "conversation_id": "2036854775807",
        "user_message_id": "2036854775808",
    }
    assert payloads[2].model_dump(mode="json")["assistant_message_id"] == "2036854775809"


def test_completed_payload_accepts_only_stop_or_interrupt():
    assert CompletedPayload(assistant_message_id=1).finish_reason == "stop"
    assert CompletedPayload(
        assistant_message_id=1, finish_reason="interrupt"
    ).finish_reason == "interrupt"

    with pytest.raises(ValidationError):
        CompletedPayload(assistant_message_id=1, finish_reason="length")


def test_completion_finish_reason_alias_is_reused_by_completed_payload():
    assert "CompletionFinishReason" in app.contracts.chat.__all__
    assert get_args(CompletionFinishReason) == ("stop", "interrupt")
    assert CompletedPayload.model_fields["finish_reason"].annotation == (
        CompletionFinishReason
    )
    assert "finish_reason: CompletionFinishReason" in getsource(CompletedPayload)

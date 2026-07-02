import json

import pytest


def test_document_convert_requested_serializes_doc_id_as_string():
    from app.modules.document.events import (
        DOCUMENT_CONVERT_REQUESTED_TOPIC,
        DocumentConvertRequested,
    )

    event = DocumentConvertRequested.create(doc_id=42)

    payload = json.loads(event.to_json())

    assert payload["event_type"] == "document.convert.requested"
    assert payload["doc_id"] == "42"
    assert payload["event_id"]
    assert payload["occurred_at"].endswith("Z")
    assert DOCUMENT_CONVERT_REQUESTED_TOPIC == "document.convert.requested"


def test_document_convert_requested_rejects_wrong_event_type():
    from app.modules.document.events import DocumentConvertRequested

    with pytest.raises(ValueError, match="unsupported event_type"):
        DocumentConvertRequested.from_json(
            json.dumps(
                {
                    "event_id": "event-1",
                    "event_type": "wrong.type",
                    "doc_id": "42",
                    "occurred_at": "2026-07-02T00:00:00Z",
                }
            )
        )

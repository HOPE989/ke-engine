import pytest
from pydantic import ValidationError


def _schema_symbols():
    from app.contracts.document.http import DocumentChunkRequest, DocumentChunkResponse
    from app.domains.document.shared.schemas import (
        InvalidDocumentChunkRequest,
        validate_document_chunk_request,
    )

    return (
        DocumentChunkRequest,
        DocumentChunkResponse,
        InvalidDocumentChunkRequest,
        validate_document_chunk_request,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"overlap": 10},
        {"chunk_size": 100},
        {"chunk_size": "100", "overlap": 10},
        {"chunk_size": 100.5, "overlap": 10},
        {"chunk_size": 100, "overlap": "10"},
        {"chunk_size": 100, "overlap": 10.5},
    ],
)
def test_chunk_request_rejects_missing_or_non_integer_fields(payload):
    DocumentChunkRequest, _, _, _ = _schema_symbols()

    with pytest.raises(ValidationError):
        DocumentChunkRequest.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"chunk_size": 0, "overlap": 0},
        {"chunk_size": -1, "overlap": 0},
        {"chunk_size": 100, "overlap": -1},
        {"chunk_size": 100, "overlap": 100},
        {"chunk_size": 100, "overlap": 101},
    ],
)
def test_chunk_request_rejects_invalid_size_overlap_relationship(payload):
    DocumentChunkRequest, _, InvalidDocumentChunkRequest, validate_request = _schema_symbols()
    request = DocumentChunkRequest.model_validate(payload)

    with pytest.raises(InvalidDocumentChunkRequest):
        validate_request(request)


def test_chunk_request_accepts_positive_size_and_smaller_non_negative_overlap():
    DocumentChunkRequest, _, _, validate_request = _schema_symbols()
    request = DocumentChunkRequest.model_validate({"chunk_size": 100, "overlap": 20})

    assert validate_request(request) is request


def test_chunk_response_serializes_document_id_as_string():
    _, DocumentChunkResponse, _, _ = _schema_symbols()

    response = DocumentChunkResponse(doc_id="9007199254740993", status="CHUNKED", segment_count=3)

    assert response.model_dump() == {
        "doc_id": "9007199254740993",
        "status": "CHUNKED",
        "segment_count": 3,
    }

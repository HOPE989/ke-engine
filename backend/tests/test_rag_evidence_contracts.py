import json

import pytest
from pydantic import ValidationError


def test_retrieve_evidence_request_normalizes_aliases_and_is_serializable():
    from app.domains.rag.services import RetrieveEvidenceRequest

    request = RetrieveEvidenceRequest.model_validate(
        {
            "query": "  调度规程有哪些要求？ ",
            "accessibleBy": ["mock-user", " mock-user "],
            "docIds": ["doc-2", "doc-1"],
            "conversationContext": [
                {"role": "user", "content": "我们讨论调度规程"},
                {"role": "assistant", "content": "请问具体章节？"},
            ],
            "businessIntent": "POLICY_RULE_QA",
        }
    )

    assert request.query == "调度规程有哪些要求？"
    assert request.accessible_by == ("mock-user",)
    assert request.doc_ids == ("doc-1", "doc-2")
    dumped = request.model_dump(mode="json", by_alias=True)
    assert dumped["conversationContext"][0]["role"] == "user"
    assert json.loads(json.dumps(dumped, ensure_ascii=False)) == dumped


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "", "accessibleBy": ["mock-user"]},
        {"query": "   ", "accessibleBy": ["mock-user"]},
        {"query": "问题", "accessibleBy": []},
        {"query": "问题"},
        {"query": "问题", "accessibleBy": [""]},
    ],
)
def test_retrieve_evidence_request_rejects_invalid_scope(payload):
    from app.domains.rag.services import RetrieveEvidenceRequest

    with pytest.raises(ValidationError):
        RetrieveEvidenceRequest.model_validate(payload)


def test_evidence_package_uses_minimal_alias_contract():
    from app.domains.rag.services import EvidenceItem, EvidencePackage

    package = EvidencePackage(
        query="合同付款周期？",
        standalone_query="合同付款周期",
        evidence_items=(
            EvidenceItem(
                citation_id="doc-1:chunk-2",
                content="付款周期为三十天。",
                doc_id="doc-1",
                chunk_id="chunk-2",
                file_name="合同.md",
                rerank_score=0.92,
            ),
        ),
    )

    dumped = package.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    assert dumped == {
        "query": "合同付款周期？",
        "standaloneQuery": "合同付款周期",
        "evidenceItems": [
            {
                "citationId": "doc-1:chunk-2",
                "content": "付款周期为三十天。",
                "docId": "doc-1",
                "chunkId": "chunk-2",
                "fileName": "合同.md",
                "rerankScore": 0.92,
            }
        ],
    }
    assert json.loads(json.dumps(dumped, ensure_ascii=False)) == dumped


def test_evidence_contract_does_not_expose_internal_fields():
    from app.domains.rag.services import EvidenceItem, EvidencePackage

    public_fields = {
        "query",
        "standaloneQuery",
        "evidenceItems",
    }
    item_fields = {
        "citationId",
        "content",
        "docId",
        "chunkId",
        "fileName",
        "url",
        "rerankScore",
    }
    package_schema = EvidencePackage.model_json_schema(by_alias=True)
    item_schema = EvidenceItem.model_json_schema(by_alias=True)

    assert set(package_schema["properties"]) == public_fields
    assert set(item_schema["properties"]) == item_fields
    serialized_schema = json.dumps(
        package_schema,
        ensure_ascii=False,
    ).lower()
    for forbidden in (
        "retrieval_plan",
        "diagnostics",
        "exception",
        "credential",
        "client",
        "callback",
        "trace",
    ):
        assert forbidden not in serialized_schema

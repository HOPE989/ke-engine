from types import SimpleNamespace


class FakeIdGenerator:
    def __init__(self, ids):
        self.ids = list(ids)

    def next_id(self):
        return self.ids.pop(0)


def _document():
    return SimpleNamespace(
        doc_id=42,
        doc_title="guide.pdf",
        converted_doc_url="https://files.example.com/documents/documents/42/converted/document.md",
        accessible_by="team-a",
    )


def _split_chunk(
    *,
    text,
    chunk_id="10001",
    skip_embedding=False,
    parent_chunk_id=None,
    metadata=None,
):
    from app.modules.document.chunking import MarkdownSplitChunk

    return MarkdownSplitChunk(
        chunk_id=chunk_id,
        text=text,
        langchain_metadata=metadata or {"Header 1": "Guide"},
        skip_embedding=skip_embedding,
        parent_chunk_id=parent_chunk_id,
    )


def test_segment_drafts_allocate_snowflake_id_and_reuse_string_chunk_id():
    from app.modules.document.chunking import build_segment_drafts

    drafts = build_segment_drafts(
        document=_document(),
        split_chunks=[
            _split_chunk(text="first", chunk_id="10001"),
            _split_chunk(text="second", chunk_id="10002"),
        ],
        id_generator=FakeIdGenerator([9001, 9002]),
    )

    assert [(draft.id, draft.chunk_id) for draft in drafts] == [
        (9001, "10001"),
        (9002, "10002"),
    ]


def test_segment_drafts_assign_zero_based_order_including_parent_rows():
    from app.modules.document.chunking import build_segment_drafts

    drafts = build_segment_drafts(
        document=_document(),
        split_chunks=[
            _split_chunk(text="normal-a"),
            _split_chunk(text="parent", chunk_id="10002", skip_embedding=True),
            _split_chunk(text="child-a", chunk_id="10003", parent_chunk_id="10002"),
            _split_chunk(text="child-b", chunk_id="10004", parent_chunk_id="10002"),
            _split_chunk(text="normal-b", chunk_id="10005"),
        ],
        id_generator=FakeIdGenerator([9001, 9002, 9003, 9004, 9005]),
    )

    assert [draft.text for draft in drafts] == [
        "normal-a",
        "parent",
        "child-a",
        "child-b",
        "normal-b",
    ]
    assert [draft.chunk_order for draft in drafts] == [0, 1, 2, 3, 4]
    assert drafts[1].skip_embedding is True
    assert drafts[2].metadata["parentChunkId"] == "10002"
    assert drafts[3].metadata["parentChunkId"] == "10002"


def test_segment_metadata_contains_required_document_and_chunk_fields():
    from app.modules.document.chunking import build_segment_drafts

    drafts = build_segment_drafts(
        document=_document(),
        split_chunks=[
            _split_chunk(
                text="first",
                chunk_id="10001",
                metadata={"Header 1": "Guide", "Header 2": "Install"},
            )
        ],
        id_generator=FakeIdGenerator([9001]),
    )

    metadata = drafts[0].metadata
    assert set(metadata) == {
        "skipEmbedding",
        "chunkId",
        "docId",
        "fileName",
        "url",
        "accessibleBy",
        "parentChunkId",
        "langchain",
    }
    assert metadata["fileName"] == "guide.pdf"
    assert metadata["url"] == _document().converted_doc_url
    assert metadata["accessibleBy"] == "team-a"
    assert metadata["parentChunkId"] is None
    assert metadata["langchain"] == {"Header 1": "Guide", "Header 2": "Install"}
    assert "Header 1" not in metadata


def test_segment_metadata_duplicates_selected_database_fields():
    from app.modules.document.chunking import build_segment_drafts

    drafts = build_segment_drafts(
        document=_document(),
        split_chunks=[_split_chunk(text="parent", chunk_id="10001", skip_embedding=True)],
        id_generator=FakeIdGenerator([9001]),
    )

    draft = drafts[0]
    assert draft.document_id == 42
    assert draft.chunk_id == "10001"
    assert draft.skip_embedding is True
    assert draft.metadata["docId"] == "42"
    assert draft.metadata["chunkId"] == draft.chunk_id
    assert draft.metadata["skipEmbedding"] is draft.skip_embedding

from types import SimpleNamespace

import pytest


EXPECTED_HEADERS = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
    ("####", "Header 4"),
    ("#####", "Header 5"),
    ("######", "Header 6"),
]

EXPECTED_SEPARATORS = [
    "\n\n",
    "\n",
    " ",
    ".",
    ",",
    "\u200b",
    "\uff0c",
    "\u3001",
    "\uff0e",
    "\u3002",
    "",
]


def test_markdown_header_splitter_uses_stable_configuration(monkeypatch):
    from app.modules.document import chunking

    captured = {}

    class FakeMarkdownHeaderTextSplitter:
        def __init__(self, *, headers_to_split_on, strip_headers, return_each_line):
            captured["headers_to_split_on"] = headers_to_split_on
            captured["strip_headers"] = strip_headers
            captured["return_each_line"] = return_each_line

        def split_text(self, markdown):
            return []

    monkeypatch.setattr(
        chunking,
        "MarkdownHeaderTextSplitter",
        FakeMarkdownHeaderTextSplitter,
        raising=False,
    )

    chunks = chunking.split_markdown_into_chunks("   ", chunk_size=100, overlap=0)

    assert chunks == []
    assert captured == {
        "headers_to_split_on": EXPECTED_HEADERS,
        "strip_headers": False,
        "return_each_line": False,
    }


def test_recursive_splitter_uses_request_parameters_and_stable_separators(monkeypatch):
    from app.modules.document import chunking

    captured = {}

    class FakeMarkdownHeaderTextSplitter:
        def __init__(self, **kwargs):
            pass

        def split_text(self, markdown):
            return [SimpleNamespace(page_content="x" * 20, metadata={})]

    class FakeRecursiveCharacterTextSplitter:
        def __init__(
            self,
            *,
            chunk_size,
            chunk_overlap,
            length_function,
            is_separator_regex,
            separators,
        ):
            captured["chunk_size"] = chunk_size
            captured["chunk_overlap"] = chunk_overlap
            captured["length_function"] = length_function
            captured["is_separator_regex"] = is_separator_regex
            captured["separators"] = separators

        def split_text(self, text):
            return ["child"]

    monkeypatch.setattr(
        chunking,
        "MarkdownHeaderTextSplitter",
        FakeMarkdownHeaderTextSplitter,
        raising=False,
    )
    monkeypatch.setattr(
        chunking,
        "RecursiveCharacterTextSplitter",
        FakeRecursiveCharacterTextSplitter,
        raising=False,
    )

    chunks = chunking.split_markdown_into_chunks("oversized", chunk_size=10, overlap=2)

    assert [chunk.text for chunk in chunks] == ["x" * 20, "child"]
    assert captured == {
        "chunk_size": 10,
        "chunk_overlap": 2,
        "length_function": len,
        "is_separator_regex": False,
        "separators": EXPECTED_SEPARATORS,
    }


def test_splitter_returns_normal_section_when_within_chunk_size():
    from app.modules.document.chunking import split_markdown_into_chunks

    chunks = split_markdown_into_chunks("# Guide\nshort content", chunk_size=100, overlap=0)

    assert len(chunks) == 1
    assert chunks[0].text == "# Guide\nshort content"
    assert chunks[0].skip_embedding is False
    assert chunks[0].parent_index is None
    assert chunks[0].langchain_metadata == {"Header 1": "Guide"}


def test_splitter_returns_parent_and_children_for_oversized_section():
    from app.modules.document.chunking import split_markdown_into_chunks

    markdown = "# Guide\nalpha beta gamma delta epsilon zeta eta theta"

    chunks = split_markdown_into_chunks(markdown, chunk_size=18, overlap=0)

    assert chunks[0].text == markdown
    assert chunks[0].skip_embedding is True
    assert chunks[0].parent_index is None
    assert chunks[0].langchain_metadata == {"Header 1": "Guide"}
    assert len(chunks) > 2
    for child in chunks[1:]:
        assert child.text.strip()
        assert len(child.text) <= 18
        assert child.skip_embedding is False
        assert child.parent_index == 0
        assert child.langchain_metadata == {"Header 1": "Guide"}


def test_splitter_discards_empty_chunks(monkeypatch):
    from app.modules.document import chunking

    class FakeMarkdownHeaderTextSplitter:
        def __init__(self, **kwargs):
            pass

        def split_text(self, markdown):
            return [
                SimpleNamespace(page_content="   ", metadata={}),
                SimpleNamespace(page_content="usable", metadata={"Header 1": "Guide"}),
            ]

    monkeypatch.setattr(
        chunking,
        "MarkdownHeaderTextSplitter",
        FakeMarkdownHeaderTextSplitter,
        raising=False,
    )

    chunks = chunking.split_markdown_into_chunks("ignored", chunk_size=100, overlap=0)

    assert [chunk.text for chunk in chunks] == ["usable"]


def test_splitter_returns_zero_segments_for_empty_markdown():
    from app.modules.document.chunking import split_markdown_into_chunks

    assert split_markdown_into_chunks("   ", chunk_size=100, overlap=0) == []

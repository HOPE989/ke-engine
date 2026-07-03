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


class FakeIdGenerator:
    def __init__(self, ids):
        self.ids = list(ids)

    def next_id(self):
        return self.ids.pop(0)


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

    chunks = chunking.split_markdown_into_chunks(
        "   ",
        chunk_size=100,
        overlap=0,
        id_generator=FakeIdGenerator([]),
    )

    assert chunks == []
    assert captured == {
        "headers_to_split_on": EXPECTED_HEADERS,
        "strip_headers": True,
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

    chunks = chunking.split_markdown_into_chunks(
        "oversized",
        chunk_size=10,
        overlap=2,
        id_generator=FakeIdGenerator([10001, 10002]),
    )

    assert [chunk.text for chunk in chunks] == ["x" * 20, "child"]
    assert [(chunk.chunk_id, chunk.parent_chunk_id) for chunk in chunks] == [
        ("10001", None),
        ("10002", "10001"),
    ]
    assert captured == {
        "chunk_size": 10,
        "chunk_overlap": 2,
        "length_function": len,
        "is_separator_regex": False,
        "separators": EXPECTED_SEPARATORS,
    }


def test_recursive_splitter_is_reused_for_multiple_oversized_sections(monkeypatch):
    from app.modules.document import chunking

    constructed = []
    split_inputs = []

    class FakeMarkdownHeaderTextSplitter:
        def __init__(self, **kwargs):
            pass

        def split_text(self, markdown):
            return [
                SimpleNamespace(page_content="a" * 20, metadata={"Header 1": "One"}),
                SimpleNamespace(page_content="b" * 20, metadata={"Header 1": "Two"}),
            ]

    class FakeRecursiveCharacterTextSplitter:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def split_text(self, text):
            split_inputs.append(text)
            return [text[:5]]

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

    chunks = chunking.split_markdown_into_chunks(
        "ignored",
        chunk_size=10,
        overlap=2,
        id_generator=FakeIdGenerator(range(10001, 10010)),
    )

    assert len(constructed) == 1
    assert split_inputs == ["a" * 20, "b" * 20]
    assert [chunk.parent_chunk_id for chunk in chunks] == [
        None,
        "10001",
        None,
        "10003",
    ]


def test_splitter_returns_normal_section_when_within_chunk_size():
    from app.modules.document.chunking import split_markdown_into_chunks

    chunks = split_markdown_into_chunks(
        "# Guide\nshort content",
        chunk_size=100,
        overlap=0,
        id_generator=FakeIdGenerator([10001]),
    )

    assert len(chunks) == 1
    assert chunks[0].text == "short content"
    assert chunks[0].skip_embedding is False
    assert chunks[0].chunk_id == "10001"
    assert chunks[0].parent_chunk_id is None
    assert chunks[0].langchain_metadata == {"Header 1": "Guide"}


def test_splitter_returns_parent_and_children_for_oversized_section():
    from app.modules.document.chunking import split_markdown_into_chunks

    markdown = "# Guide\nalpha beta gamma delta epsilon zeta eta theta"

    chunks = split_markdown_into_chunks(
        markdown,
        chunk_size=18,
        overlap=0,
        id_generator=FakeIdGenerator(range(10001, 10020)),
    )

    assert chunks[0].text == "alpha beta gamma delta epsilon zeta eta theta"
    assert "# Guide" not in chunks[0].text
    assert chunks[0].skip_embedding is True
    assert chunks[0].chunk_id == "10001"
    assert chunks[0].parent_chunk_id is None
    assert chunks[0].langchain_metadata == {"Header 1": "Guide"}
    assert len(chunks) > 2
    for child in chunks[1:]:
        assert child.text.strip()
        assert len(child.text) <= 18
        assert child.skip_embedding is False
        assert child.parent_chunk_id == "10001"
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

    chunks = chunking.split_markdown_into_chunks(
        "ignored",
        chunk_size=100,
        overlap=0,
        id_generator=FakeIdGenerator([10001]),
    )

    assert [chunk.text for chunk in chunks] == ["usable"]


def test_splitter_returns_zero_segments_for_empty_markdown():
    from app.modules.document.chunking import split_markdown_into_chunks

    assert (
        split_markdown_into_chunks(
            "   ",
            chunk_size=100,
            overlap=0,
            id_generator=FakeIdGenerator([]),
        )
        == []
    )

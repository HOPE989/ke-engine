from types import SimpleNamespace

import pytest


class FakeStorage:
    def __init__(self, *, payload: bytes = b"# Guide", download_error: Exception | None = None):
        self.bucket = "documents"
        self.public_base_url = "https://files.example.com"
        self.payload = payload
        self.download_error = download_error
        self.downloaded_keys = []

    async def download_bytes(self, *, object_key: str) -> bytes:
        self.downloaded_keys.append(object_key)
        if self.download_error is not None:
            raise self.download_error
        return self.payload


@pytest.mark.asyncio
async def test_load_converted_markdown_resolves_valid_public_url_to_object_key():
    from app.modules.document.chunking import load_converted_markdown

    storage = FakeStorage(payload="# Guide\ncontent".encode())
    document = SimpleNamespace(
        converted_doc_url=(
            "https://files.example.com/documents/documents/42/converted/document.md"
        )
    )

    markdown = await load_converted_markdown(document=document, storage=storage)

    assert markdown == "# Guide\ncontent"
    assert storage.downloaded_keys == ["documents/42/converted/document.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "converted_doc_url",
    [
        "https://other.example.com/documents/documents/42/converted/document.md",
        "https://files.example.com/other-bucket/documents/42/converted/document.md",
        "https://files.example.com/documents/",
    ],
)
async def test_load_converted_markdown_rejects_invalid_public_url(converted_doc_url):
    from app.modules.document.chunking import load_converted_markdown
    from app.modules.document.errors import DocumentStateConflict

    storage = FakeStorage()
    document = SimpleNamespace(converted_doc_url=converted_doc_url)

    with pytest.raises(DocumentStateConflict):
        await load_converted_markdown(document=document, storage=storage)

    assert storage.downloaded_keys == []


@pytest.mark.asyncio
@pytest.mark.parametrize("download_error", [FileNotFoundError("missing"), OSError("minio down")])
async def test_load_converted_markdown_maps_download_failures_to_unavailable(download_error):
    from app.modules.document.chunking import load_converted_markdown
    from app.modules.document.errors import ConvertedMarkdownUnavailable

    storage = FakeStorage(download_error=download_error)
    document = SimpleNamespace(
        converted_doc_url=(
            "https://files.example.com/documents/documents/42/converted/document.md"
        )
    )

    with pytest.raises(ConvertedMarkdownUnavailable):
        await load_converted_markdown(document=document, storage=storage)

    assert storage.downloaded_keys == ["documents/42/converted/document.md"]


@pytest.mark.asyncio
async def test_load_converted_markdown_maps_non_utf8_bytes_to_invalid():
    from app.modules.document.chunking import load_converted_markdown
    from app.modules.document.errors import ConvertedMarkdownInvalid

    storage = FakeStorage(payload=b"\xff\xfe\xfa")
    document = SimpleNamespace(
        converted_doc_url=(
            "https://files.example.com/documents/documents/42/converted/document.md"
        )
    )

    with pytest.raises(ConvertedMarkdownInvalid):
        await load_converted_markdown(document=document, storage=storage)

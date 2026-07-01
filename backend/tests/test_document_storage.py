from io import BytesIO

import pytest


def _storage_module():
    from app.modules.document import storage

    return storage


def test_document_storage_object_keys_and_public_urls():
    storage = _storage_module()

    assert (
        storage.original_object_key(doc_id=42, safe_filename="guide.md")
        == "documents/42/original/guide.md"
    )
    assert (
        storage.converted_markdown_object_key(doc_id=42)
        == "documents/42/converted/document.md"
    )
    assert (
        storage.asset_object_key(doc_id=42, image_filename="../figures/page-1.png")
        == "documents/42/assets/page-1.png"
    )
    assert (
        storage.public_object_url(
            public_base_url="https://files.example.com/",
            bucket="documents",
            object_key="documents/42/original/guide.md",
        )
        == "https://files.example.com/documents/documents/42/original/guide.md"
    )


class FakeMinioClient:
    def __init__(self):
        self.put_object_calls = []
        self.get_object_calls = []
        self.object_bytes = b""

    def put_object(self, bucket, object_name, data, length, content_type):
        assert isinstance(data, BytesIO)
        self.put_object_calls.append(
            {
                "bucket": bucket,
                "object_name": object_name,
                "content": data.read(),
                "length": length,
                "content_type": content_type,
            }
        )

    def get_object(self, bucket, object_name):
        self.get_object_calls.append({"bucket": bucket, "object_name": object_name})
        return BytesIO(self.object_bytes)


def test_storage_adapter_does_not_own_bucket_lifecycle():
    storage = _storage_module()
    client = FakeMinioClient()
    adapter = storage.DocumentObjectStorage(
        client=client,
        bucket="documents",
        public_base_url="https://files.example.com",
    )

    assert not hasattr(adapter, "ensure_bucket")


@pytest.mark.asyncio
async def test_storage_adapter_uploads_bytes_through_threadpool(monkeypatch):
    storage = _storage_module()
    client = FakeMinioClient()
    threadpool_calls = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        threadpool_calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(storage, "run_in_threadpool", fake_run_in_threadpool)
    adapter = storage.DocumentObjectStorage(
        client=client,
        bucket="documents",
        public_base_url="https://files.example.com",
    )

    url = await adapter.upload_bytes(
        object_key="documents/42/converted/document.md",
        content=b"# converted",
        content_type="text/markdown",
    )

    assert threadpool_calls == ["put_object"]
    assert client.put_object_calls == [
        {
            "bucket": "documents",
            "object_name": "documents/42/converted/document.md",
            "content": b"# converted",
            "length": len(b"# converted"),
            "content_type": "text/markdown",
        }
    ]
    assert url == "https://files.example.com/documents/documents/42/converted/document.md"


@pytest.mark.asyncio
async def test_storage_adapter_downloads_bytes_through_threadpool(monkeypatch):
    storage = _storage_module()
    client = FakeMinioClient()
    client.object_bytes = b"%PDF-1.7"
    threadpool_calls = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        threadpool_calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(storage, "run_in_threadpool", fake_run_in_threadpool)
    adapter = storage.DocumentObjectStorage(
        client=client,
        bucket="documents",
        public_base_url="https://files.example.com",
    )

    content = await adapter.download_bytes(object_key="documents/42/original/guide.pdf")

    assert threadpool_calls == ["_read_object"]
    assert client.get_object_calls == [
        {"bucket": "documents", "object_name": "documents/42/original/guide.pdf"}
    ]
    assert content == b"%PDF-1.7"

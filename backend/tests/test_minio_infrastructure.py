import pytest


class FakeMinioClient:
    def __init__(self, *, bucket_exists: bool):
        self._bucket_exists = bucket_exists
        self.bucket_exists_calls = []
        self.make_bucket_calls = []
        self.set_bucket_policy_calls = []

    def bucket_exists(self, bucket):
        self.bucket_exists_calls.append(bucket)
        return self._bucket_exists

    def make_bucket(self, bucket):
        self.make_bucket_calls.append(bucket)

    def set_bucket_policy(self, bucket, policy):
        self.set_bucket_policy_calls.append({"bucket": bucket, "policy": policy})


@pytest.mark.asyncio
async def test_minio_bucket_initializer_creates_missing_bucket_through_threadpool(monkeypatch):
    from app.infrastructure import minio as minio_infra

    client = FakeMinioClient(bucket_exists=False)
    threadpool_calls = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        threadpool_calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(minio_infra, "run_in_threadpool", fake_run_in_threadpool)

    await minio_infra.ensure_minio_bucket(client, "documents")

    assert threadpool_calls == ["bucket_exists", "make_bucket", "set_bucket_policy"]
    assert client.bucket_exists_calls == ["documents"]
    assert client.make_bucket_calls == ["documents"]
    assert client.set_bucket_policy_calls == [
        {
            "bucket": "documents",
            "policy": minio_infra.public_read_bucket_policy("documents"),
        }
    ]


@pytest.mark.asyncio
async def test_minio_bucket_initializer_skips_existing_bucket(monkeypatch):
    from app.infrastructure import minio as minio_infra

    client = FakeMinioClient(bucket_exists=True)
    threadpool_calls = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        threadpool_calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(minio_infra, "run_in_threadpool", fake_run_in_threadpool)

    await minio_infra.ensure_minio_bucket(client, "documents")

    assert threadpool_calls == ["bucket_exists", "set_bucket_policy"]
    assert client.bucket_exists_calls == ["documents"]
    assert client.make_bucket_calls == []
    assert client.set_bucket_policy_calls == [
        {
            "bucket": "documents",
            "policy": minio_infra.public_read_bucket_policy("documents"),
        }
    ]


def test_public_read_bucket_policy_allows_only_object_reads():
    from app.infrastructure.minio import public_read_bucket_policy

    policy = public_read_bucket_policy("documents")

    assert '"Effect":"Allow"' in policy
    assert '"Action":["s3:GetObject"]' in policy
    assert '"Resource":["arn:aws:s3:::documents/*"]' in policy
    assert "PutObject" not in policy
    assert "DeleteObject" not in policy

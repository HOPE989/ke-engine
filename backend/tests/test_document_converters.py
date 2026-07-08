from io import BytesIO
import importlib
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.domains.document.shared.errors import DocumentConversionFailed
from app.domains.document.shared.file_types import DocumentFileType
from app.domains.document.shared.models import DocumentStatus


def make_zip(entries: dict[str, bytes | str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def load_converters_module():
    try:
        return importlib.import_module("app.domains.document.components.converters")
    except ModuleNotFoundError as exc:
        if exc.name == "app.domains.document.components.converters":
            pytest.fail("app.domains.document.components.converters module is missing")
        raise


def make_document(
    *,
    file_type: DocumentFileType | str,
    doc_title: str,
    doc_url: str | None = "https://files.example.com/documents/documents/42/original/source",
):
    return SimpleNamespace(
        doc_id=42,
        doc_title=doc_title,
        upload_user="alice",
        accessible_by="team-a",
        description="Document description",
        knowledge_base_type="DOCUMENT_SEARCH",
        file_type=file_type,
        doc_url=doc_url,
        converted_doc_url=None,
        status=DocumentStatus.UPLOADED.value,
    )


class FailingStorage:
    async def download_bytes(self, *, object_key):
        raise AssertionError(f"storage download must not be called: {object_key}")

    async def upload_bytes(self, *, object_key, content, content_type):
        raise AssertionError(f"storage upload must not be called: {object_key}")


class FailingMinerUClient:
    async def request_zip(self, *, filename, content):
        raise AssertionError(f"MinerU must not be called: {filename}")


class RecordingStorage:
    def __init__(self, *, downloads=None, fail_on_download=False):
        self.downloads = dict(downloads or {})
        self.fail_on_download = fail_on_download
        self.download_calls = []
        self.uploads = []

    async def download_bytes(self, *, object_key):
        self.download_calls.append(object_key)
        if self.fail_on_download:
            raise RuntimeError("download failed")
        return self.downloads[object_key]

    async def upload_bytes(self, *, object_key, content, content_type):
        self.uploads.append(
            {
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        return f"https://files.example.com/documents/{object_key}"


class RecordingMinerUClient:
    def __init__(self, zip_bytes):
        self.zip_bytes = zip_bytes
        self.calls = []

    async def request_zip(self, *, filename, content):
        self.calls.append({"filename": filename, "content": content})
        return self.zip_bytes


@pytest.mark.asyncio
async def test_plain_text_converter_returns_doc_url_without_storage_or_mineru_calls():
    converters = load_converters_module()
    converter = converters.PlainTextConverter()
    document = make_document(
        file_type=DocumentFileType.PLAIN_TEXT,
        doc_title="notes.md",
        doc_url="https://files.example.com/documents/documents/42/original/notes.md",
    )

    converted_url = await converter.convert_document(
        document=document,
        storage=FailingStorage(),
        mineru_client=FailingMinerUClient(),
    )

    assert converter.supports(DocumentFileType.PLAIN_TEXT)
    assert converted_url == "https://files.example.com/documents/documents/42/original/notes.md"


@pytest.mark.asyncio
async def test_plain_text_converter_raises_when_doc_url_is_missing():
    converters = load_converters_module()
    converter = converters.PlainTextConverter()
    document = make_document(
        file_type=DocumentFileType.PLAIN_TEXT,
        doc_title="notes.md",
        doc_url=None,
    )

    with pytest.raises(DocumentConversionFailed):
        await converter.convert_document(
            document=document,
            storage=FailingStorage(),
            mineru_client=FailingMinerUClient(),
        )


@pytest.mark.asyncio
async def test_pdf_converter_downloads_original_calls_mineru_and_uploads_markdown():
    converters = load_converters_module()
    converter = converters.PdfDocumentConverter()
    document = make_document(file_type=DocumentFileType.PDF, doc_title="guide.pdf")
    storage = RecordingStorage(
        downloads={"documents/42/original/guide.pdf": b"%PDF-1.7"},
    )
    mineru_client = RecordingMinerUClient(make_zip({"guide.md": "# Guide"}))

    converted_url = await converter.convert_document(
        document=document,
        storage=storage,
        mineru_client=mineru_client,
    )

    assert converter.supports(DocumentFileType.PDF)
    assert storage.download_calls == ["documents/42/original/guide.pdf"]
    assert mineru_client.calls == [{"filename": "guide.pdf", "content": b"%PDF-1.7"}]
    assert storage.uploads[-1] == {
        "object_key": "documents/42/converted/document.md",
        "content": b"# Guide",
        "content_type": "text/markdown",
    }
    assert converted_url == "https://files.example.com/documents/documents/42/converted/document.md"


@pytest.mark.asyncio
async def test_word_converter_supports_enum_type_and_calls_mineru_for_docx_original():
    converters = load_converters_module()
    converter = converters.WordDocumentConverter()
    document = make_document(file_type=DocumentFileType.WORD, doc_title="guide.docx")
    storage = RecordingStorage(
        downloads={"documents/42/original/guide.docx": b"docx-bytes"},
    )
    mineru_client = RecordingMinerUClient(make_zip({"guide.md": "# Guide"}))

    converted_url = await converter.convert_document(
        document=document,
        storage=storage,
        mineru_client=mineru_client,
    )

    assert converter.supports(DocumentFileType.WORD)
    assert converter.supports("word")
    assert storage.download_calls == ["documents/42/original/guide.docx"]
    assert mineru_client.calls == [{"filename": "guide.docx", "content": b"docx-bytes"}]
    assert converted_url == "https://files.example.com/documents/documents/42/converted/document.md"


@pytest.mark.asyncio
async def test_mineru_converter_wraps_original_download_failure():
    converters = load_converters_module()
    converter = converters.PdfDocumentConverter()
    document = make_document(file_type=DocumentFileType.PDF, doc_title="guide.pdf")

    with pytest.raises(DocumentConversionFailed):
        await converter.convert_document(
            document=document,
            storage=RecordingStorage(fail_on_download=True),
            mineru_client=RecordingMinerUClient(make_zip({"guide.md": "# Guide"})),
        )


@pytest.mark.asyncio
async def test_excel_converter_reuses_origin_url_for_excel_and_csv_without_storage_or_mineru_calls():
    converters = load_converters_module()
    converter = converters.ExcelConverter()
    excel_document = make_document(
        file_type=DocumentFileType.EXCEL,
        doc_title="sheet.xlsx",
        doc_url="https://files.example.com/documents/documents/42/original/sheet.xlsx",
    )
    csv_document = make_document(
        file_type=DocumentFileType.CSV,
        doc_title="data.csv",
        doc_url="https://files.example.com/documents/documents/42/original/data.csv",
    )

    assert converter.supports(DocumentFileType.EXCEL)
    assert converter.supports("excel")
    assert converter.supports(DocumentFileType.CSV)
    assert converter.supports("csv")
    assert (
        await converter.convert_document(
            document=excel_document,
            storage=FailingStorage(),
            mineru_client=FailingMinerUClient(),
        )
        == "https://files.example.com/documents/documents/42/original/sheet.xlsx"
    )
    assert (
        await converter.convert_document(
            document=csv_document,
            storage=FailingStorage(),
            mineru_client=FailingMinerUClient(),
        )
        == "https://files.example.com/documents/documents/42/original/data.csv"
    )


@pytest.mark.asyncio
async def test_excel_converter_raises_when_origin_url_is_missing():
    converters = load_converters_module()
    converter = converters.ExcelConverter()
    document = make_document(
        file_type=DocumentFileType.EXCEL,
        doc_title="sheet.xlsx",
        doc_url=None,
    )

    with pytest.raises(DocumentConversionFailed):
        await converter.convert_document(
            document=document,
            storage=FailingStorage(),
            mineru_client=FailingMinerUClient(),
        )


def test_document_converter_factory_selects_supported_converter_and_rejects_unknown_type():
    converters = load_converters_module()
    plain_text_converter = converters.PlainTextConverter()
    excel_converter = converters.ExcelConverter()
    factory = converters.DocumentConverterFactory([excel_converter, plain_text_converter])

    assert factory.converter_for(DocumentFileType.PLAIN_TEXT) is plain_text_converter
    assert factory.converter_for(DocumentFileType.EXCEL) is excel_converter
    assert factory.converter_for(DocumentFileType.CSV) is excel_converter
    assert factory.converter_for("excel") is excel_converter
    assert factory.converter_for("csv") is excel_converter

    with pytest.raises(DocumentConversionFailed):
        factory.converter_for("ppt")


def test_create_default_document_converter_factory_registers_known_converters():
    converters = load_converters_module()
    factory = converters.create_default_document_converter_factory()

    assert isinstance(factory.converter_for(DocumentFileType.PLAIN_TEXT), converters.PlainTextConverter)
    assert isinstance(factory.converter_for(DocumentFileType.PDF), converters.PdfDocumentConverter)
    assert isinstance(factory.converter_for(DocumentFileType.WORD), converters.WordDocumentConverter)
    assert isinstance(factory.converter_for(DocumentFileType.EXCEL), converters.ExcelConverter)
    assert isinstance(factory.converter_for(DocumentFileType.CSV), converters.ExcelConverter)
    assert isinstance(factory.converter_for("word"), converters.WordDocumentConverter)
    assert isinstance(factory.converter_for("excel"), converters.ExcelConverter)
    assert isinstance(factory.converter_for("csv"), converters.ExcelConverter)

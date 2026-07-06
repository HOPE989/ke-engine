import pytest


class FakeMagikaOutput:
    def __init__(self, *, ct_label: str, mime_type: str):
        self.ct_label = ct_label
        self.mime_type = mime_type


class FakeMagikaResult:
    def __init__(self, *, ct_label: str, mime_type: str):
        self.output = FakeMagikaOutput(ct_label=ct_label, mime_type=mime_type)


class FakeMagikaClient:
    def __init__(self, result=None, failure=None):
        self.result = result
        self.failure = failure
        self.seen_content = None

    def identify_bytes(self, content):
        self.seen_content = content
        if self.failure is not None:
            raise self.failure
        return self.result


def _file_type_modules():
    from app.modules.document.errors import (
        FileTypeDetectionFailed,
        UnsupportedDocumentFileType,
    )
    from app.modules.document.file_types import (
        DocumentFileType,
        detect_document_file_type,
    )

    return (
        detect_document_file_type,
        DocumentFileType,
        FileTypeDetectionFailed,
        UnsupportedDocumentFileType,
    )


@pytest.mark.parametrize(
    "result",
    [
        FakeMagikaResult(ct_label="pdf", mime_type="application/octet-stream"),
        FakeMagikaResult(ct_label="unknown", mime_type="application/pdf"),
    ],
)
def test_magika_pdf_detection_is_accepted(result):
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()
    magika_client = FakeMagikaClient(result=result)

    detected = detect_document_file_type(
        filename="guide.pdf",
        content=b"%PDF-1.7",
        upload_content_type="application/octet-stream",
        magika_client=magika_client,
    )

    assert detected == DocumentFileType.PDF
    assert magika_client.seen_content == b"%PDF-1.7"


def test_magika_markdown_detection_is_accepted_as_plain_text():
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()

    detected = detect_document_file_type(
        filename="guide",
        content=b"# Guide",
        upload_content_type="application/octet-stream",
        magika_client=FakeMagikaClient(
            result=FakeMagikaResult(ct_label="markdown", mime_type="text/markdown")
        ),
    )

    assert detected == DocumentFileType.PLAIN_TEXT


def test_upload_mime_markdown_is_accepted_even_when_magika_misclassifies():
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()

    detected = detect_document_file_type(
        filename="营业额.md",
        content=(
            "2026年5月21号的营业额是110k元。\n"
            "C:\\Program Files\\WindowsApps\\OpenAI.Codex_*\\app\\Codex.exe\n"
        ).encode(),
        upload_content_type="text/markdown",
        magika_client=FakeMagikaClient(
            result=FakeMagikaResult(ct_label="powershell", mime_type="application/x-powershell")
        ),
    )

    assert detected == DocumentFileType.PLAIN_TEXT


@pytest.mark.parametrize(
    "filename,upload_content_type",
    [
        ("guide.doc", "application/msword"),
        (
            "guide.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_word_upload_mime_is_accepted_even_when_magika_is_generic(
    filename,
    upload_content_type,
):
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()

    detected = detect_document_file_type(
        filename=filename,
        content=b"word-bytes",
        upload_content_type=upload_content_type,
        magika_client=FakeMagikaClient(
            result=FakeMagikaResult(ct_label="unknown", mime_type="application/octet-stream")
        ),
    )

    assert detected == DocumentFileType.WORD


@pytest.mark.parametrize(
    "filename,result",
    [
        ("guide.doc", FakeMagikaResult(ct_label="doc", mime_type="application/octet-stream")),
        ("guide.docx", FakeMagikaResult(ct_label="docx", mime_type="application/octet-stream")),
        ("guide.docx", FakeMagikaResult(ct_label="word", mime_type="application/octet-stream")),
        ("upload.bin", FakeMagikaResult(ct_label="docx", mime_type="application/octet-stream")),
        ("guide.doc", FakeMagikaResult(ct_label="unknown", mime_type="application/msword")),
        (
            "guide.docx",
            FakeMagikaResult(
                ct_label="unknown",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
            ),
        ),
    ],
)
def test_magika_word_detection_is_accepted(filename, result):
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()

    detected = detect_document_file_type(
        filename=filename,
        content=b"word-bytes",
        upload_content_type="application/octet-stream",
        magika_client=FakeMagikaClient(result=result),
    )

    assert detected == DocumentFileType.WORD


def test_docx_extension_without_word_evidence_is_rejected():
    detect_document_file_type, _, _, UnsupportedDocumentFileType = _file_type_modules()

    with pytest.raises(UnsupportedDocumentFileType):
        detect_document_file_type(
            filename="guide.docx",
            content=b"\x89PNG",
            upload_content_type="image/png",
            magika_client=FakeMagikaClient(
                result=FakeMagikaResult(ct_label="png", mime_type="image/png")
            ),
        )


@pytest.mark.parametrize(
    "filename,upload_content_type,result",
    [
        (
            "sheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            FakeMagikaResult(
                ct_label="xlsx",
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ),
        (
            "sheet.xls",
            "application/vnd.ms-excel",
            FakeMagikaResult(ct_label="xls", mime_type="application/vnd.ms-excel"),
        ),
    ],
)
def test_excel_files_are_still_rejected(filename, upload_content_type, result):
    detect_document_file_type, _, _, UnsupportedDocumentFileType = _file_type_modules()

    with pytest.raises(UnsupportedDocumentFileType):
        detect_document_file_type(
            filename=filename,
            content=b"excel-bytes",
            upload_content_type=upload_content_type,
            magika_client=FakeMagikaClient(result=result),
        )


@pytest.mark.parametrize(
    "result",
    [
        FakeMagikaResult(ct_label="xls", mime_type="application/octet-stream"),
        FakeMagikaResult(ct_label="xlsx", mime_type="application/octet-stream"),
        FakeMagikaResult(ct_label="excel", mime_type="application/octet-stream"),
        FakeMagikaResult(ct_label="unknown", mime_type="application/vnd.ms-excel"),
        FakeMagikaResult(
            ct_label="unknown",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_excel_content_with_word_upload_mime_is_rejected(result):
    detect_document_file_type, _, _, UnsupportedDocumentFileType = _file_type_modules()

    with pytest.raises(UnsupportedDocumentFileType):
        detect_document_file_type(
            filename="sheet.xlsx",
            content=b"excel-bytes",
            upload_content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            magika_client=FakeMagikaClient(result=result),
        )


@pytest.mark.parametrize("filename", ["guide.md", "guide.markdown", "notes.txt"])
def test_generic_text_with_supported_extension_is_accepted(filename):
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()

    detected = detect_document_file_type(
        filename=filename,
        content=b"plain text",
        upload_content_type="application/octet-stream",
        magika_client=FakeMagikaClient(
            result=FakeMagikaResult(ct_label="txt", mime_type="text/plain")
        ),
    )

    assert detected == DocumentFileType.PLAIN_TEXT


def test_unsupported_file_type_is_rejected():
    detect_document_file_type, _, _, UnsupportedDocumentFileType = _file_type_modules()

    with pytest.raises(UnsupportedDocumentFileType):
        detect_document_file_type(
            filename="image.png",
            content=b"\x89PNG",
            upload_content_type="image/png",
            magika_client=FakeMagikaClient(
                result=FakeMagikaResult(ct_label="png", mime_type="image/png")
            ),
        )


def test_magika_runtime_failure_is_normalized():
    detect_document_file_type, _, FileTypeDetectionFailed, _ = _file_type_modules()

    with pytest.raises(FileTypeDetectionFailed):
        detect_document_file_type(
            filename="guide.pdf",
            content=b"%PDF-1.7",
            upload_content_type="application/octet-stream",
            magika_client=FakeMagikaClient(failure=RuntimeError("model failed")),
        )

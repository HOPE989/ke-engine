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
        magika_client=magika_client,
    )

    assert detected == DocumentFileType.PDF
    assert magika_client.seen_content == b"%PDF-1.7"


def test_magika_markdown_detection_is_accepted_as_plain_text():
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()

    detected = detect_document_file_type(
        filename="guide",
        content=b"# Guide",
        magika_client=FakeMagikaClient(
            result=FakeMagikaResult(ct_label="markdown", mime_type="text/markdown")
        ),
    )

    assert detected == DocumentFileType.PLAIN_TEXT


@pytest.mark.parametrize("filename", ["guide.md", "guide.markdown", "notes.txt"])
def test_generic_text_with_supported_extension_is_accepted(filename):
    detect_document_file_type, DocumentFileType, _, _ = _file_type_modules()

    detected = detect_document_file_type(
        filename=filename,
        content=b"plain text",
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
            magika_client=FakeMagikaClient(failure=RuntimeError("model failed")),
        )

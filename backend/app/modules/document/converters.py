from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from app.modules.document.errors import DocumentConversionFailed
from app.modules.document.file_types import DocumentFileType
from app.modules.document.schemas import ValidatedDocumentUpload
from app.modules.document.storage import original_object_key
from app.modules.document.workflow import convert_mineru_document


def _file_type_value(file_type: DocumentFileType | str) -> str:
    if isinstance(file_type, DocumentFileType):
        return file_type.value
    return str(file_type)


class BaseDocumentConverter(ABC):
    @abstractmethod
    def supports(self, file_type: DocumentFileType | str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        raise NotImplementedError


class DocumentConverterFactory:
    def __init__(self, converters: Iterable[BaseDocumentConverter]):
        self._converters = tuple(converters)

    def converter_for(self, file_type: DocumentFileType | str) -> BaseDocumentConverter:
        for converter in self._converters:
            if converter.supports(file_type):
                return converter
        raise DocumentConversionFailed()

    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        converter = self.converter_for(document.file_type)
        return await converter.convert_document(
            document=document,
            storage=storage,
            mineru_client=mineru_client,
            image_describer=image_describer,
        )


class PlainTextConverter(BaseDocumentConverter):
    def supports(self, file_type: DocumentFileType | str) -> bool:
        return _file_type_value(file_type) == DocumentFileType.PLAIN_TEXT.value

    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        if not document.doc_url:
            raise DocumentConversionFailed()
        return document.doc_url


class MinerUDocumentConverter(BaseDocumentConverter):
    supported_file_type: DocumentFileType | str | None = None

    def supports(self, file_type: DocumentFileType | str) -> bool:
        if self.supported_file_type is None:
            return False
        return _file_type_value(file_type) == _file_type_value(self.supported_file_type)

    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        object_key = original_object_key(
            doc_id=document.doc_id,
            safe_filename=document.doc_title,
        )
        try:
            content = await storage.download_bytes(object_key=object_key)
        except Exception as exc:
            raise DocumentConversionFailed() from exc

        upload = ValidatedDocumentUpload(
            doc_title=document.doc_title,
            safe_filename=document.doc_title,
            upload_user=document.upload_user,
            accessible_by=document.accessible_by,
            content_type="application/octet-stream",
            content=content,
            size_bytes=len(content),
        )
        return await convert_mineru_document(
            doc_id=document.doc_id,
            upload=upload,
            storage=storage,
            mineru_client=mineru_client,
            image_describer=image_describer,
        )


class PdfDocumentConverter(MinerUDocumentConverter):
    supported_file_type = DocumentFileType.PDF


class WordDocumentConverter(MinerUDocumentConverter):
    supported_file_type = "word"


class ExcelConverter(BaseDocumentConverter):
    def supports(self, file_type: DocumentFileType | str) -> bool:
        return _file_type_value(file_type) == "excel"

    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        raise DocumentConversionFailed()


default_document_converter_factory = DocumentConverterFactory(
    [
        PlainTextConverter(),
        PdfDocumentConverter(),
        WordDocumentConverter(),
        ExcelConverter(),
    ]
)

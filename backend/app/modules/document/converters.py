"""文档转换器分发与具体转换实现。

本模块把“文档类型如何转换”的判断集中到 converter factory：
调用方只需要传入已通过文件类型识别的 document，factory 会根据
``document.file_type`` 选择对应转换器，并把转换依赖继续透传下去。
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from app.modules.document.errors import DocumentConversionFailed
from app.modules.document.file_types import DocumentFileType
from app.modules.document.schemas import ValidatedDocumentUpload
from app.modules.document.storage import original_object_key
from app.modules.document.workflow import convert_mineru_document


def _file_type_value(file_type: DocumentFileType | str) -> str:
    """把枚举或字符串形式的文件类型统一成业务值字符串。"""

    if isinstance(file_type, DocumentFileType):
        return file_type.value
    return str(file_type)


class BaseDocumentConverter(ABC):
    """所有文档转换器的统一协议。

    子类需要声明自己支持的文件类型，并实现具体转换过程。这样 factory
    可以只依赖抽象协议完成分发，不需要知道 PDF、Word 或纯文本的细节。
    """

    @abstractmethod
    def supports(self, file_type: DocumentFileType | str) -> bool:
        """判断当前转换器是否能处理传入的业务文件类型。"""

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
        """执行转换并返回转换后文档 URL。

        参数说明：
        - ``document``：数据库中已创建的文档记录，至少需要包含 doc_id、
          doc_title、file_type、doc_url、upload_user、accessible_by 等字段。
        - ``storage``：对象存储适配器，用于读取原始文件或写入转换结果。
        - ``mineru_client``：MinerU 客户端，用于 PDF/Word 转 Markdown。
        - ``image_describer``：可选的图片描述依赖，透传给 MinerU 工作流。

        转换失败时抛出 ``DocumentConversionFailed``，由上层流程统一回滚状态。
        """

        raise NotImplementedError


class DocumentConverterFactory:
    """按文件类型选择文档转换器的工厂。

    factory 负责“选择谁来转换”，具体转换细节仍交给各 converter 子类。
    这样新增文件类型时只需要新增转换器并注册到工厂，调用方无需增加
    if/elif 分支。
    """

    def __init__(self, converters: Iterable[BaseDocumentConverter]):
        """保存转换器列表，并冻结为 tuple 以避免运行中被外部修改。"""

        self._converters = tuple(converters)

    def converter_for(self, file_type: DocumentFileType | str) -> BaseDocumentConverter:
        """查找第一个支持指定文件类型的转换器。

        注册顺序有意义：如果多个转换器声明支持同一类型，排在前面的转换器
        会优先被使用。没有匹配项时抛出稳定领域异常，由上层统一处理。
        """

        # 1. 逐个询问已注册转换器是否支持当前文件类型。
        for converter in self._converters:
            if converter.supports(file_type):
                # 2. 命中后立即返回，后续转换器不再参与判断。
                return converter
        # 3. 所有转换器都不支持时，报告为文档转换失败。
        raise DocumentConversionFailed()

    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        """根据 document.file_type 分发转换请求并返回转换结果 URL。

        这里不直接读取或写入文件，只完成两件事：
        1. 根据文档记录中的文件类型选择 converter；
        2. 把 document、storage、MinerU、图片描述器等依赖原样交给 converter。
        """

        # 1. 从文档记录读取业务文件类型，定位具体转换器。
        converter = self.converter_for(document.file_type)
        # 2. 委托转换器执行真实转换，factory 自身不关心转换细节。
        return await converter.convert_document(
            document=document,
            storage=storage,
            mineru_client=mineru_client,
            image_describer=image_describer,
        )


class PlainTextConverter(BaseDocumentConverter):
    """纯文本/Markdown 转换器。

    纯文本上传后已经是可消费内容，不需要进入 MinerU；转换结果 URL
    直接复用原始文件 URL。
    """

    def supports(self, file_type: DocumentFileType | str) -> bool:
        """仅支持业务文件类型 ``plain_text``。"""

        return _file_type_value(file_type) == DocumentFileType.PLAIN_TEXT.value

    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        """返回原始文档 URL，缺失 URL 时视为转换失败。"""

        # 1. 纯文本链路依赖上传阶段保存的原始文件 URL。
        if not document.doc_url:
            raise DocumentConversionFailed()
        # 2. 不调用对象存储下载，也不调用 MinerU，直接返回原始 URL。
        return document.doc_url


class MinerUDocumentConverter(BaseDocumentConverter):
    """基于 MinerU 的文档转换基类。

    PDF、Word 等二进制文档需要先从对象存储取回原始文件，再调用
    ``convert_mineru_document`` 生成 Markdown 并上传转换结果。子类只需配置
    ``supported_file_type``，即可复用这一套转换流程。
    """

    supported_file_type: DocumentFileType | str | None = None

    def supports(self, file_type: DocumentFileType | str) -> bool:
        """按子类声明的 ``supported_file_type`` 判断是否支持。"""

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
        """下载原始文件，构造上传对象，并交给 MinerU 工作流转换。"""

        # 1. 根据文档 ID 和安全文件名还原上传阶段保存原件的对象存储 key。
        object_key = original_object_key(
            doc_id=document.doc_id,
            safe_filename=document.doc_title,
        )
        try:
            # 2. 读取原始二进制内容；下载失败统一包装成领域转换异常。
            content = await storage.download_bytes(object_key=object_key)
        except Exception as exc:
            raise DocumentConversionFailed() from exc

        # 3. 将数据库文档记录和原始字节重新组装成 MinerU 工作流需要的上传对象。
        upload = ValidatedDocumentUpload(
            doc_title=document.doc_title,
            safe_filename=document.doc_title,
            upload_user=document.upload_user,
            accessible_by=document.accessible_by,
            content_type="application/octet-stream",
            content=content,
            size_bytes=len(content),
        )
        # 4. 调用统一 MinerU 转换流程：请求 zip、提取 Markdown、上传转换结果。
        return await convert_mineru_document(
            doc_id=document.doc_id,
            upload=upload,
            storage=storage,
            mineru_client=mineru_client,
            image_describer=image_describer,
        )


class PdfDocumentConverter(MinerUDocumentConverter):
    """PDF 文档转换器，复用 MinerU 转 Markdown 流程。"""

    supported_file_type = DocumentFileType.PDF


class WordDocumentConverter(MinerUDocumentConverter):
    """Word 文档转换器，复用 MinerU 转 Markdown 流程。"""

    supported_file_type = DocumentFileType.WORD


class ExcelConverter(BaseDocumentConverter):
    """Excel 文档转换器占位实现。

    当前文件类型识别和 factory 已预留 Excel 分发路径，但业务上尚未实现
    Excel 转 Markdown 的实际能力，因此命中后会明确抛出转换失败。
    """

    def supports(self, file_type: DocumentFileType | str) -> bool:
        """仅支持业务文件类型 ``excel``。"""

        return _file_type_value(file_type) == DocumentFileType.EXCEL.value

    async def convert_document(
        self,
        *,
        document: Any,
        storage: Any,
        mineru_client: Any,
        image_describer: Any | None = None,
    ) -> str:
        """Excel 转换暂未实现，调用时直接抛出稳定领域异常。"""

        # 1. 保留显式 converter，便于调用方知道 Excel 类型已被识别。
        # 2. 在真实转换能力完成前，统一按转换失败处理。
        raise DocumentConversionFailed()


def create_default_document_converter_factory() -> DocumentConverterFactory:
    """创建默认文档转换器工厂。

    该函数只负责装配 converter 注册表，不在业务转换热路径中隐式执行。
    Kafka worker 等宿主进程应在启动期调用它，并把返回的 factory 放入进程级
    runtime，再由转换链路显式消费。
    """

    # 1. 集中注册当前业务支持的转换器。
    # 2. 注册顺序也是匹配优先级，前面的 converter 会优先命中。
    return DocumentConverterFactory(
        [
            PlainTextConverter(),
            PdfDocumentConverter(),
            WordDocumentConverter(),
            ExcelConverter(),
        ]
    )

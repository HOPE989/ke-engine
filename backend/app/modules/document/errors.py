"""文档上传领域的稳定异常类型。

这些异常只表达领域失败原因，HTTP 状态码和响应文案由 router 层统一映射。
"""


class DocumentStateConflict(Exception):
    """生命周期状态更新不符合预期状态时抛出。"""


class UnsupportedDocumentFileType(Exception):
    """文件类型检测结果不在当前支持范围内时抛出。"""


class FileTypeDetectionFailed(Exception):
    """Magika 文件类型检测运行失败时抛出。"""


class DocumentStorageFailed(Exception):
    """原始文件或转换结果写入对象存储失败时抛出。"""


class DocumentConversionFailed(Exception):
    """PDF 转换无法产出可用 Markdown 时抛出。"""


class DocumentStateRollbackFailed(Exception):
    """转换失败后无法将文档状态回滚到 UPLOADED 时抛出。"""

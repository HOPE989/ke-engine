"""文档上传领域的稳定异常类型。

这些异常只表达领域失败原因，HTTP 状态码和响应文案由 router 层统一映射。
"""


class DocumentStateConflict(Exception):
    """生命周期状态更新不符合预期状态时抛出。"""


class DocumentNotFound(Exception):
    """请求的文档不存在时抛出。"""


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


class DocumentConversionLockBusy(Exception):
    """文档转换锁被占用且当前消息应保留重试。"""


class ConvertedMarkdownUnavailable(Exception):
    """转换后的 Markdown 对象无法从对象存储读取时抛出。"""


class ConvertedMarkdownInvalid(Exception):
    """转换后的 Markdown 字节不是有效 UTF-8 时抛出。"""


class ChunkPersistenceFailed(Exception):
    """分段持久化或完成状态更新失败时抛出。"""


class ChunkSplittingFailed(Exception):
    """LangChain Markdown 分段失败时抛出。"""


class ChunkLockUnavailable(Exception):
    """文档切分 Redis 锁基础设施不可用时抛出。"""


class DocumentVectorStorageDispatchFailed(Exception):
    """文档向量存储事件派发失败时抛出。"""


class DataQueryTableNameConflict(Exception):
    """DATA_QUERY 逻辑表名在同一 namespace 下已被占用。"""


class DataQueryUploadBusy(Exception):
    """DATA_QUERY 上传 namespace 锁已被占用。"""


class DataQueryUploadLockUnavailable(Exception):
    """DATA_QUERY 上传锁基础设施不可用。"""


class DataQueryIngestionFailed(Exception):
    """DATA_QUERY spreadsheet 关系表导入失败。"""

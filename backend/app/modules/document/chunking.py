"""文档切分前的 Markdown 读取与分段能力。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import unquote, urlparse

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_text_splitters.base import TextSplitter

from app.modules.document.errors import (
    ChunkLockUnavailable,
    ChunkSplittingFailed,
    ConvertedMarkdownInvalid,
    ConvertedMarkdownUnavailable,
    DocumentStateConflict,
)
from app.modules.document.file_types import DocumentFileType
from app.modules.document.markdown import parse_markdown_image_references

HEADERS_TO_SPLIT_ON = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
    ("####", "Header 4"),
    ("#####", "Header 5"),
    ("######", "Header 6"),
]

RECURSIVE_SEPARATORS = [
    "\n\n",
    "\n",
    " ",
    ".",
    ",",
    "\u200b",
    "\uff0c",
    "\u3001",
    "\uff0e",
    "\u3002",
    "",
]

logger = logging.getLogger(__name__)


def _file_type_value(file_type: DocumentFileType | str) -> str:
    if isinstance(file_type, DocumentFileType):
        return file_type.value
    return str(file_type)


@dataclass(frozen=True, slots=True)
class MarkdownSplitChunk:
    """Markdown splitter 产出的待持久化分段。"""

    chunk_id: str
    text: str
    langchain_metadata: dict[str, Any]
    skip_embedding: bool
    parent_chunk_id: str | None


@dataclass(frozen=True, slots=True)
class SegmentDraft:
    """准备批量写入 knowledge_segment 的分段数据。"""

    id: int
    chunk_id: str
    text: str
    document_id: int
    chunk_order: int
    embedding_id: str | None
    status: str
    metadata: dict[str, Any]
    skip_embedding: bool


class _LocalIdGenerator:
    def __init__(self) -> None:
        self._next_value = 0

    def next_id(self) -> int:
        self._next_value += 1
        return self._next_value


class MarkdownHeaderParentTextSplitter(TextSplitter):
    """按 Markdown 标题切父块，超长父块再按递归字符切子块。"""

    def __init__(self, *, chunk_size: int, overlap: int) -> None:
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            length_function=len,
        )

    def split_text(self, text: str) -> list[str]:
        """返回 LangChain TextSplitter 兼容的文本切分结果。"""

        return [
            chunk.text
            for chunk in self.split_chunks(
                text,
                id_generator=_LocalIdGenerator(),
            )
        ]

    def split_chunks(self, text: str, *, id_generator: Any) -> list[MarkdownSplitChunk]:
        """返回业务持久化需要的 parent/child chunk 结构。"""

        header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=HEADERS_TO_SPLIT_ON,
            strip_headers=True,
            return_each_line=False,
        )
        chunks: list[MarkdownSplitChunk] = []
        recursive_splitter: RecursiveCharacterTextSplitter | None = None

        for section in header_splitter.split_text(text):
            section_text = section.page_content
            if not section_text.strip():
                continue

            metadata = dict(section.metadata)
            if len(section_text) <= self._chunk_size:
                chunks.append(
                    MarkdownSplitChunk(
                        chunk_id=str(id_generator.next_id()),
                        text=section_text,
                        langchain_metadata=metadata,
                        skip_embedding=False,
                        parent_chunk_id=None,
                    )
                )
                continue

            if recursive_splitter is None:
                recursive_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self._chunk_size,
                    chunk_overlap=self._chunk_overlap,
                    length_function=len,
                    is_separator_regex=False,
                    separators=RECURSIVE_SEPARATORS,
                )
            parent_chunk_id = str(id_generator.next_id())
            chunks.append(
                MarkdownSplitChunk(
                    chunk_id=parent_chunk_id,
                    text=section_text,
                    langchain_metadata=metadata,
                    skip_embedding=True,
                    parent_chunk_id=None,
                )
            )
            for child_text in recursive_splitter.split_text(section_text):
                if not child_text.strip():
                    continue
                chunks.append(
                    MarkdownSplitChunk(
                        chunk_id=str(id_generator.next_id()),
                        text=child_text,
                        langchain_metadata=metadata,
                        skip_embedding=False,
                        parent_chunk_id=parent_chunk_id,
                    )
                )

        return chunks


class DocumentSplitterFactory:
    """按文件类型唯一选择文档切分器。"""

    def __init__(self) -> None:
        self._builders: dict[str, Callable[..., Any]] = {}

    def register(
        self,
        *,
        file_type: DocumentFileType | str,
        splitter_builder: Callable[..., Any],
    ) -> None:
        normalized_file_type = _file_type_value(file_type)
        if normalized_file_type in self._builders:
            raise ValueError(f"splitter for file_type {normalized_file_type} already registered")
        self._builders[normalized_file_type] = splitter_builder

    def splitter_for(
        self,
        file_type: DocumentFileType | str,
        *,
        chunk_size: int,
        overlap: int,
    ) -> Any:
        builder = self._builders.get(_file_type_value(file_type))
        if builder is None:
            raise ChunkSplittingFailed()
        return builder(chunk_size=chunk_size, overlap=overlap)


def create_default_document_splitter_factory() -> DocumentSplitterFactory:
    """创建进程启动期使用的默认 splitter 注册表。"""

    factory = DocumentSplitterFactory()
    for file_type in (
        DocumentFileType.PLAIN_TEXT,
        DocumentFileType.PDF,
        DocumentFileType.WORD,
    ):
        factory.register(
            file_type=file_type,
            splitter_builder=MarkdownHeaderParentTextSplitter,
        )
    return factory


async def run_with_document_chunk_lock(
    *,
    lock: Any,
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    """持有单文档切分锁执行一个异步操作。"""

    try:
        acquired = lock.acquire(blocking=False)
    except Exception as exc:
        raise ChunkLockUnavailable() from exc

    if not acquired:
        raise DocumentStateConflict()

    try:
        return await operation()
    finally:
        try:
            lock.release()
        except Exception:
            logger.exception("failed to release document chunk lock")


def _resolve_converted_object_key(*, converted_doc_url: str, storage: Any, doc_id: int) -> str:
    base = urlparse(storage.public_base_url.rstrip("/"))
    url = urlparse(converted_doc_url)
    if url.scheme != base.scheme or url.netloc != base.netloc:
        raise DocumentStateConflict()

    base_path = base.path.rstrip("/")
    url_path = unquote(url.path)
    if base_path:
        if url_path != base_path and not url_path.startswith(f"{base_path}/"):
            raise DocumentStateConflict()
        relative_path = url_path[len(base_path) :].lstrip("/")
    else:
        relative_path = url_path.lstrip("/")

    bucket, separator, object_key = relative_path.partition("/")
    if bucket != storage.bucket or not separator or not object_key.strip("/"):
        raise DocumentStateConflict()
    if not object_key.startswith(f"documents/{doc_id}/"):
        raise DocumentStateConflict()
    return object_key


async def load_converted_markdown(*, document: Any, storage: Any) -> str:
    """解析 converted_doc_url，下载并返回 UTF-8 Markdown 文本。"""

    converted_doc_url = getattr(document, "converted_doc_url", None)
    if not converted_doc_url:
        raise DocumentStateConflict()

    object_key = _resolve_converted_object_key(
        converted_doc_url=converted_doc_url,
        storage=storage,
        doc_id=document.doc_id,
    )
    try:
        content = await storage.download_bytes(object_key=object_key)
    except Exception as exc:
        raise ConvertedMarkdownUnavailable() from exc

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConvertedMarkdownInvalid() from exc


def split_markdown_into_chunks(
    markdown: str,
    *,
    chunk_size: int,
    overlap: int,
    id_generator: Any,
) -> list[MarkdownSplitChunk]:
    """按 Markdown header 和递归字符长度切分 Markdown。"""

    return MarkdownHeaderParentTextSplitter(
        chunk_size=chunk_size,
        overlap=overlap,
    ).split_chunks(markdown, id_generator=id_generator)


def build_segment_drafts(
    *,
    document: Any,
    split_chunks: list[MarkdownSplitChunk],
    id_generator: Any,
) -> list[SegmentDraft]:
    """把 splitter 输出转换为可持久化的 segment drafts。"""

    drafts: list[SegmentDraft] = []
    for chunk_order, split_chunk in enumerate(split_chunks):
        row_id = id_generator.next_id()
        chunk_id = split_chunk.chunk_id
        metadata = {
            "skipEmbedding": split_chunk.skip_embedding,
            "chunkId": chunk_id,
            "docId": str(document.doc_id),
            "fileName": document.doc_title,
            "url": document.converted_doc_url,
            "accessibleBy": document.accessible_by,
            "parentChunkId": split_chunk.parent_chunk_id,
            "langchain": dict(split_chunk.langchain_metadata),
            "images": _extract_markdown_images(
                text=split_chunk.text,
                document=document,
            ),
        }
        drafts.append(
            SegmentDraft(
                id=row_id,
                chunk_id=chunk_id,
                text=split_chunk.text,
                document_id=document.doc_id,
                chunk_order=chunk_order,
                embedding_id=None,
                status="STORED",
                metadata=metadata,
                skip_embedding=split_chunk.skip_embedding,
            )
        )

    return drafts


def _extract_markdown_images(*, text: str, document: Any) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for reference in parse_markdown_image_references(text):
        image = {
            "url": reference.target,
            "alt": reference.alt,
            "source": "markdown-image",
        }
        object_key = _derive_document_image_object_key(
            image_url=reference.target,
            document=document,
        )
        if object_key is not None:
            image["objectKey"] = object_key
        images.append(image)
    return images


def _derive_document_image_object_key(*, image_url: str, document: Any) -> str | None:
    converted_doc_url = getattr(document, "converted_doc_url", None)
    if not converted_doc_url:
        return None

    converted = urlparse(converted_doc_url)
    image = urlparse(image_url)
    if image.scheme != converted.scheme or image.netloc != converted.netloc:
        return None

    doc_prefix = ["documents", str(document.doc_id)]
    converted_parts = [part for part in unquote(converted.path).split("/") if part]
    image_parts = [part for part in unquote(image.path).split("/") if part]
    marker_index = _find_subsequence(converted_parts, doc_prefix)
    if marker_index is None or marker_index == 0:
        return None

    base_and_bucket_parts = converted_parts[:marker_index]
    if image_parts[: len(base_and_bucket_parts)] != base_and_bucket_parts:
        return None

    object_key_parts = image_parts[len(base_and_bucket_parts) :]
    if object_key_parts[:2] != doc_prefix:
        return None

    return "/".join(object_key_parts)


def _find_subsequence(parts: list[str], subsequence: list[str]) -> int | None:
    for index in range(0, len(parts) - len(subsequence) + 1):
        if parts[index : index + len(subsequence)] == subsequence:
            return index
    return None

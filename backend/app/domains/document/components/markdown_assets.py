"""MinerU ZIP 中 Markdown 与图片资源的解析工具。"""

import mimetypes
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable
from zipfile import BadZipFile, ZipFile

from app.domains.document.shared.errors import DocumentConversionFailed

MARKDOWN_SUFFIXES = {".md", ".markdown"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SUPPORTED_IMAGE_LINK_PATTERN = re.compile(r"!\[([^\]\\]*)\]\(([^()<>\s]+)\)")
IMAGE_PARSE_ERROR_DESCRIPTION = "图片解析错误"


@dataclass(frozen=True)
class MarkdownImageReference:
    alt: str
    target: str
    start: int
    end: int


def _normalized_archive_path(name: str) -> PurePosixPath:
    """将 ZIP 成员路径归一化为安全的相对 POSIX 路径。"""

    normalized_name = name.replace("\\", "/")
    path = PurePosixPath(normalized_name)
    # 拒绝绝对路径、空路径段和目录穿越，防止 ZIP 写出临时目录。
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DocumentConversionFailed()
    return path


def extract_mineru_zip(zip_bytes: bytes, target_dir: Path) -> list[Path]:
    """安全解压 MinerU ZIP，并返回解出的相对文件路径列表。"""

    extracted_paths: list[Path] = []
    seen_paths: set[str] = set()
    root = target_dir.resolve()

    try:
        with ZipFile(BytesIO(zip_bytes)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue

                # 1. 先做路径语义校验，重复路径会导致覆盖，必须拒绝。
                relative_path = _normalized_archive_path(member.filename)
                normalized_key = relative_path.as_posix().lower()
                if normalized_key in seen_paths:
                    raise DocumentConversionFailed()
                seen_paths.add(normalized_key)

                # 2. resolve 后再次确认目标仍在临时目录下。
                target_path = (root / Path(*relative_path.parts)).resolve()
                if root not in target_path.parents:
                    raise DocumentConversionFailed()

                # 3. 只在所有安全校验通过后写入文件。
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(archive.read(member))
                extracted_paths.append(Path(*relative_path.parts))
    except (BadZipFile, OSError) as exc:
        raise DocumentConversionFailed() from exc

    return extracted_paths


def _normalized_path(path: Path) -> str:
    """将相对路径转换为用于排序和比较的小写 POSIX 字符串。"""

    return path.as_posix().lower()


def select_markdown_path(markdown_paths: list[Path], pdf_stem: str) -> Path:
    """按 MinerU 输出约定从多个 Markdown 中选择主文档。"""

    if not markdown_paths:
        raise DocumentConversionFailed()

    normalized_stem = pdf_stem.strip().lower()
    # 选择优先级：文件名匹配 PDF stem，其次目录名匹配，最后稳定排序兜底。
    basename_matches = [
        path for path in markdown_paths if path.stem.lower() == normalized_stem
    ]
    if basename_matches:
        return sorted(basename_matches, key=_normalized_path)[0]

    parent_matches = [
        path
        for path in markdown_paths
        if any(parent.name.lower() == normalized_stem for parent in path.parents)
    ]
    if parent_matches:
        return sorted(parent_matches, key=_normalized_path)[0]

    return sorted(markdown_paths, key=_normalized_path)[0]


def image_content_type(path: Path) -> str:
    """根据图片文件名推断上传到 MinIO 时使用的 content type。"""

    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def parse_markdown_image_references(markdown_text: str) -> list[MarkdownImageReference]:
    """解析 MinerU 风格的受限 Markdown 图片引用。

    这里故意只支持 OpenSpec 声明的简单内联图片语法：
    `![alt](target)` 和 `![](target)`。复杂 CommonMark 形式不在本次范围内。
    start/end 会在后续重写时用于按原文切片拼接，避免正则替换误伤非目标文本。
    """

    return [
        MarkdownImageReference(
            alt=match.group(1),
            target=match.group(2),
            start=match.start(),
            end=match.end(),
        )
        for match in SUPPORTED_IMAGE_LINK_PATTERN.finditer(markdown_text)
    ]


def _image_lookup(mapping: dict[str, str], target: str) -> str | None:
    """用 MinerU 引用路径查找图片处理结果。

    MinerU Markdown 可能写 `images/page-1.png`，而上传对象只用 basename
    `page-1.png` 生成 asset key。调用方会同时写入完整相对路径和 basename，
    这里也按同样规则兜底查找，确保两种引用都能命中同一张图片。
    """

    normalized_target = target.replace("\\", "/").lstrip("./")
    return mapping.get(normalized_target) or mapping.get(Path(normalized_target).name)


def rewrite_markdown_image_links(
    markdown_text: str,
    image_urls: dict[str, str],
    *,
    image_descriptions: dict[str, str] | None = None,
    on_missing_image: Callable[[MarkdownImageReference], None] | None = None,
) -> str:
    """将 Markdown 中的本地图片链接改写为 MinIO 公网 URL。

    替换规则：
    1. 外链图片保持原 target 和原 alt，不下载、不描述。
    2. 本地图片上传成功且描述成功时，target 改为 MinIO URL，alt 改为描述文本。
    3. 本地图片上传失败、缺失，或描述失败时，target 尽量保留可用值，
       alt 统一写成 `图片解析错误`。

    实现上不直接使用 `re.sub`，而是用 parser 返回的 start/end 分段拼接。
    这样可以只替换受支持图片引用，其他 Markdown 内容和不支持的图片语法会原样保留。
    """

    descriptions = image_descriptions or {}
    pieces: list[str] = []
    previous_end = 0
    for reference in parse_markdown_image_references(markdown_text):
        # 先追加上一个图片引用结束到当前图片引用开始之间的原文。
        # 这段可能包含普通 Markdown、不支持的图片语法或任意正文，必须原样保留。
        pieces.append(markdown_text[previous_end : reference.start])
        raw_target = reference.target.strip()

        if "://" in raw_target:
            # 绝对 URL 被视为外部图片。按需求不能抓取远端内容，也没有本地文件可描述，
            # 因此只把当前引用按规范化后的 target/alt 拼回去。
            pieces.append(f"![{reference.alt}]({raw_target})")
            previous_end = reference.end
            continue

        # 本地图片：先找上传后的 MinIO URL。找不到说明图片缺失、读取失败、
        # 上传失败，或者 Markdown 引用了 ZIP 中不存在的文件。
        url = _image_lookup(image_urls, raw_target)
        if url is None:
            if on_missing_image is not None:
                on_missing_image(reference)
            # URL 不可用时，不能凭空生成预览地址，所以保留原始 target；
            # 但 alt 要显式标记图片处理失败，避免继续显示旧的 mock 文案。
            pieces.append(f"![{IMAGE_PARSE_ERROR_DESCRIPTION}]({raw_target})")
            previous_end = reference.end
            continue

        # URL 已经可用，但描述可能失败或未返回有效文本。
        # 这种情况下仍保留可预览的 MinIO URL，只把 alt 降级为图片解析错误。
        alt = _image_lookup(descriptions, raw_target) or IMAGE_PARSE_ERROR_DESCRIPTION
        pieces.append(f"![{alt}]({url})")
        previous_end = reference.end

    # 追加最后一个图片引用之后的剩余原文。
    pieces.append(markdown_text[previous_end:])
    return "".join(pieces)

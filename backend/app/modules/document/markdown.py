"""MinerU ZIP 中 Markdown 与图片资源的解析工具。"""

import mimetypes
import re
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from app.modules.document.errors import DocumentConversionFailed

MARKDOWN_SUFFIXES = {".md", ".markdown"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


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


def rewrite_markdown_image_links(markdown_text: str, image_urls: dict[str, str]) -> str:
    """将 Markdown 中的图片链接改写为 MinIO 公网 URL。"""

    def replace(match: re.Match[str]) -> str:
        """替换单个 Markdown 图片链接。"""

        raw_target = match.group(1).strip()
        if "://" in raw_target:
            return f"![图片描述]({raw_target})"

        # 相对路径先按路径匹配，再按文件名兜底，以兼容 MinerU 的不同引用格式。
        normalized_target = raw_target.replace("\\", "/").lstrip("./")
        url = image_urls.get(normalized_target) or image_urls.get(Path(normalized_target).name)
        if url is None:
            raise DocumentConversionFailed()
        return f"![图片描述]({url})"

    return IMAGE_LINK_PATTERN.sub(replace, markdown_text)

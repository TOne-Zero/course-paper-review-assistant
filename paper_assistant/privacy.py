"""默认不记录论文/模型原文；只清理应用明确托管的文件，不触及原文件。"""

import logging
import stat
from pathlib import Path

from paper_assistant.config import PROJECT_ROOT


MANAGED_DIRECTORIES = ("uploads", "exports", ".runtime/private", ".runtime/pdf-validation")
LEGACY_PRIVATE_PATTERNS = ("source-first-page.png", "source-page-*.png", "正文提取_已验证.txt", "文章逐页解析_已验证.json", "article_validation.json")


def configure_private_logging() -> None:
    prefixes = ("httpx", "httpcore", "pdfminer", "pypdf", "pdfplumber")
    names = set(logging.Logger.manager.loggerDict) | set(prefixes)
    for name in names:
        if name.startswith(prefixes):
            logger = logging.getLogger(name)
            logger.disabled = True
            logger.setLevel(logging.CRITICAL + 1)


def clear_managed_files(root: Path = PROJECT_ROOT) -> dict:
    root = root.resolve()
    deleted = failed = 0

    def remove(path: Path, boundary: Path):
        nonlocal deleted, failed
        if not path.exists() and not path.is_symlink():
            return
        try:
            # 每个最终目标在递归前验证，拒绝链接/Windows junction，不跟随到工作区外。
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or not resolved.is_relative_to(boundary.resolve()):
                failed += 1
                return
            attributes = path.stat(follow_symlinks=False)
            if path.is_symlink() or getattr(attributes, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                failed += 1
                return
            if path.is_dir():
                for child in tuple(path.iterdir()):
                    remove(child, boundary)
                if not any(path.iterdir()):
                    path.rmdir()
            else:
                path.unlink()
                deleted += 1
        except OSError:
            failed += 1

    for relative in MANAGED_DIRECTORIES:
        directory = root / relative
        remove(directory, directory)
    runtime = root / ".runtime"
    if (runtime.exists() and runtime.resolve().is_relative_to(root) and not runtime.is_symlink()
            and not getattr(runtime.stat(follow_symlinks=False), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
        for pattern in LEGACY_PRIVATE_PATTERNS:
            for path in runtime.glob(pattern):
                remove(path, runtime)
    return {"deleted_files": deleted, "not_removed": failed}

"""构建可交接的源码包：明确纳入项目文件，排除密钥、原论文和运行数据。"""

import argparse
import hashlib
import json
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from paper_assistant import __version__


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = "结课论文评价助手"
MANIFEST = "交接清单.json"
ROOT_FILES = {"app.py", "启动应用.cmd", "README.md", "进度.md", "OPEN_SOURCE.md", "requirements.txt", "requirements-demo.txt", ".env.example", ".gitignore", "给同事_先看这里.md", "PRODUCT.md", "DESIGN.md"}
ROOT_FILES |= {"启动完整应用.cmd", "启动旧版Streamlit.cmd"}
FRONTEND_FILES = {"package.json", "package-lock.json", "index.html", "vite.config.ts", "tsconfig.json", "tailwind.config.ts", "postcss.config.cjs", "README.md", "PRODUCT.md", "CONTRACT.md", "DESIGN.md", "启动前端预览.cmd", ".npmrc", ".gitignore"}
DIRECTORIES = {
    "assets": {".jpg", ".css", ".js", ".json", ".md"},
    "paper_assistant": {".py", ".ps1"}, "scripts": {".py"}, "tests": {".py"},
    "rubrics": {".json"}, "format_rules": {".json", ".md"},
    "references": {".md", ".json", ".bib"}, "docs": {".md"},
}
SPECIAL_FILES = {".streamlit/config.toml", "examples/demo_paper.json", "examples/演示论文_原创虚构.pdf", ".impeccable/design.json"}


def deliverable(relative: PurePosixPath) -> bool:
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative) or ":" in str(relative):
        return False
    if len(relative.parts) == 1:
        return relative.name in ROOT_FILES
    if relative.parts[0] == 'frontend-preview':
        parts = relative.parts[1:]
        if len(parts) == 1:
            return parts[0] in FRONTEND_FILES
        if parts[0] in {'src', 'public', 'dist-app'}:
            return relative.suffix in {'.ts','.tsx','.css','.js','.html','.json','.woff2','.txt'} and not any(part.startswith('.') for part in parts[1:])
        return '/'.join(parts) in {'.impeccable/design.json', '.impeccable/surface-briefs.md'}
    if relative.as_posix() in SPECIAL_FILES:
        return True
    return (relative.parts[0] in DIRECTORIES and relative.suffix in DIRECTORIES[relative.parts[0]]
            and not any(part.startswith(".") or part in {"__pycache__", "local", "user_settings"} for part in relative.parts[1:]))


def collect_files(root: Path) -> dict[str, bytes]:
    root = root.resolve()
    files = {}
    candidates = {root / name for name in ROOT_FILES | SPECIAL_FILES if (root / name).exists()}
    for directory in DIRECTORIES:
        candidates.update((root / directory).rglob("*"))
    frontend = root / 'frontend-preview'
    candidates.update(frontend / name for name in FRONTEND_FILES if (frontend / name).exists())
    for directory in ('src','public','dist-app','.impeccable'):
        candidates.update((frontend / directory).rglob('*'))
    for path in sorted(candidates):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if not deliverable(relative):
            continue
        # 检查最终文件及其所有祖先，防止链接把工作区外的内容带入交接包。
        for ancestor in (path, *path.parents):
            if ancestor == root:
                break
            attributes = ancestor.stat(follow_symlinks=False)
            if ancestor.is_symlink() or getattr(attributes, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                raise ValueError("交接文件包含链接或重解析点，未打包。")
        if not path.resolve().is_relative_to(root) or not path.is_file():
            continue
        content = path.read_bytes()
        if relative.name == ".env.example":
            for line in content.decode("utf-8-sig").splitlines():
                assignment = line.strip().removeprefix("export ").split("=", 1)
                if len(assignment) == 2 and assignment[0].strip() == "MODEL_API_KEY" and assignment[1].strip():
                    raise ValueError("环境示例的密钥字段必须为空，未打包。")
        files[relative.as_posix()] = content
    for required in ("app.py", "README.md", "requirements.txt", ".env.example"):
        if required not in files:
            raise ValueError("缺少交接必需文件，未打包。")
    return files


def verify_package(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("压缩包CRC校验失败。")
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("压缩包存在重名条目。")
        manifest_name = f"{PACKAGE_ROOT}/{MANIFEST}"
        manifest = json.loads(archive.read(manifest_name))
        expected = {f"{PACKAGE_ROOT}/{item['path']}": item for item in manifest["files"]}
        if len(expected) != len(manifest["files"]) or set(names) != set(expected) | {manifest_name}:
            raise ValueError("压缩包清单与实际文件不一致。")
        for name, item in expected.items():
            relative = PurePosixPath(item["path"])
            if not deliverable(relative):
                raise ValueError("压缩包包含不允许交接的路径。")
            content = archive.read(name)
            if len(content) != item["bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("压缩包文件哈希不一致。")
        return manifest


def build_package(root: Path = ROOT, output: Path | None = None) -> Path:
    root = root.resolve()
    output = output or root / "交付包" / f"结课论文评价助手_v{__version__}_交接包.zip"
    output = output.resolve()
    if not output.is_relative_to(root) or output.exists():
        raise ValueError("交接包须写到项目目录内且不能覆盖已有文件。")
    files = collect_files(root)
    manifest = {
        "project": PACKAGE_ROOT, "version": __version__, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files), "files": [{"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                                             for name, content in files.items()],
        "excluded": [".env及真实密钥", "原始论文和私有分析结果", "上传/导出/运行目录", "虚拟环境和缓存", "教师本地配置副本", "旧压缩包"],
        "notice": "源码包，不包含Python运行时或离线依赖；请先阅读给同事_先看这里.md。清单哈希用于完整性核对，不代表数字签名。",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in files.items():
            archive.writestr(f"{PACKAGE_ROOT}/{name}", content)
        archive.writestr(f"{PACKAGE_ROOT}/{MANIFEST}", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    verify_package(output)
    return output


def main():
    parser = argparse.ArgumentParser(description="构建或校验项目交接压缩包")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        manifest = verify_package(args.verify)
        print(json.dumps({"valid": True, "version": manifest["version"], "files": manifest["file_count"]}, ensure_ascii=False))
    else:
        output = build_package(output=args.output)
        print(json.dumps({"archive": str(output), "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

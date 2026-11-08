import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_project import build_package, collect_files, verify_package


class PackageTests(unittest.TestCase):
    def test_word_converter_is_included_without_local_scoring_settings(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);self.fixture(root)
            for item in ('paper_assistant/word_to_pdf.ps1','rubrics/user_settings/real.json'):
                path=root/item;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
            files=collect_files(root)
            self.assertIn('paper_assistant/word_to_pdf.ps1',files)
            self.assertNotIn('rubrics/user_settings/real.json',files)

    def test_react_sources_and_build_are_kept_without_runtime_or_secrets(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);self.fixture(root)
            public={'frontend-preview/package.json','frontend-preview/src/api.ts','frontend-preview/dist-app/index.html','frontend-preview/dist-app/assets/font.woff2','frontend-preview/public/licenses/OFL.txt','启动完整应用.cmd'}
            private={'frontend-preview/.env','frontend-preview/node_modules/private.json','frontend-preview/.impeccable/review/report.json','frontend-preview/.runtime/session.json'}
            for item in public|private:
                path=root/item;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'public' if item in public else b'PRIVATE')
            files=collect_files(root)
            self.assertTrue(public.issubset(files));self.assertFalse(private.intersection(files))

    def test_entrance_assets_travel_with_source_package(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            assets = {'assets/entrance/library.jpg': b'library-photo', 'assets/entrance/pages.jpg': b'book-photo',
                      'assets/entrance/entrance.css': b'entrance-style', 'assets/entrance/entrance.js': b'entrance-motion',
                      'assets/entrance/SOURCES.md': b'photo-sources'}
            for relative, content in assets.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            files = collect_files(root)
            self.assertTrue(assets.items() <= files.items())

    def fixture(self, root):
        for name in ("app.py", "README.md", "requirements.txt", ".env.example", "paper_assistant/ui.py", "examples/演示论文_原创虚构.pdf"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MODEL_API_KEY=\n" if name == ".env.example" else b"fixture")

    def test_archive_keeps_runtime_files_and_excludes_private_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            for item in (".env", ".streamlit/secrets.toml", ".runtime/private/report.json", "uploads/private.pdf", "exports/grade.json",
                         "examples/private.pdf", "rubrics/local/course.json", "paper_assistant/__pycache__/x.pyc"):
                path = root / item
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("DO_NOT_INCLUDE_PRIVATE_CONTENT", encoding="utf-8")
            output = build_package(root)
            manifest = verify_package(output)
            self.assertEqual(manifest["file_count"], 6)
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(any(b"DO_NOT_INCLUDE_PRIVATE_CONTENT" in archive.read(name) for name in archive.namelist()))
                self.assertIn("结课论文评价助手/examples/演示论文_原创虚构.pdf", archive.namelist())

    def test_nonempty_example_key_and_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            (root / ".env.example").write_text("MODEL_API_KEY=not-a-real-test-key\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                collect_files(root)
            (root / ".env.example").write_text("MODEL_API_KEY=\n", encoding="utf-8")
            output = build_package(root)
            with self.assertRaises(ValueError):
                build_package(root, output)

    def test_unlisted_archive_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            output = build_package(root)
            with zipfile.ZipFile(output, "a") as archive:
                archive.writestr("结课论文评价助手/.env", b"do not share")
            with self.assertRaises(ValueError):
                verify_package(output)

    def test_design_sources_are_kept_without_review_artifacts(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            for item in ("PRODUCT.md", "DESIGN.md", ".impeccable/design.json"):
                path = root / item
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("design-source", encoding="utf-8")
            review = root / ".impeccable/review/private-grade.json"
            review.parent.mkdir(parents=True)
            review.write_text("DO_NOT_SHARE_REVIEW_REPORT", encoding="utf-8")
            output = build_package(root)
            paths = {item["path"] for item in verify_package(output)["files"]}
            self.assertTrue({"PRODUCT.md", "DESIGN.md", ".impeccable/design.json"}.issubset(paths))
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(any(b"DO_NOT_SHARE_REVIEW_REPORT" in archive.read(name) for name in archive.namelist()))

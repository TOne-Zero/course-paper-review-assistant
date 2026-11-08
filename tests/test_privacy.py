import logging
import os
import tempfile
import unittest
from pathlib import Path

from paper_assistant.privacy import clear_managed_files, configure_private_logging


class PrivacyTests(unittest.TestCase):
    def test_cleanup_removes_only_managed_results_and_preserves_configs_and_sources(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            removable = ["uploads/paper.pdf", "exports/report.json", ".runtime/private/analysis.json", ".runtime/pdf-validation/body.txt", ".runtime/source-page-2.png"]
            protected = [".env", "app.py", "rubrics/local/course.json", "format_rules/rule.json", "examples/demo.pdf", ".runtime/app.pid", ".runtime/app.stdout.log", "original.pdf"]
            for relative in removable + protected:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test content", encoding="utf-8")
            outcome = clear_managed_files(root)
            self.assertEqual(outcome["deleted_files"], len(removable))
            self.assertTrue(all(not (root / item).exists() for item in removable))
            self.assertTrue(all((root / item).exists() for item in protected))

    def test_cleanup_does_not_follow_links_outside_workspace(self):
        with tempfile.TemporaryDirectory() as name, tempfile.TemporaryDirectory() as other:
            root, outside = Path(name), Path(other)
            secret = outside / "keep.txt"
            secret.write_text("keep", encoding="utf-8")
            try:
                os.symlink(outside, root / "uploads", target_is_directory=True)
            except OSError:
                self.skipTest("此 Windows 环境不允许建立测试符号链接。")
            outcome = clear_managed_files(root)
            self.assertTrue(secret.exists())
            self.assertGreater(outcome["not_removed"], 0)
            (root / "uploads").unlink()

    def test_default_library_logging_does_not_record_paper_or_http_debug_data(self):
        configure_private_logging()
        for name in ("httpx", "httpcore", "pdfminer.pdfinterp", "pypdf"):
            self.assertGreater(logging.getLogger(name).getEffectiveLevel(), logging.CRITICAL)

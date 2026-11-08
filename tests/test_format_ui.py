import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from paper_assistant.config import PROJECT_ROOT
from paper_assistant.routes import DEMO_PAGE
from tests.pdf_fixture import make_pdf
from tests.test_pdf_parser import CHINESE_PAGES


class FormatInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"ANALYSIS_MODE": "mock", "PDF_TEXT_ENGINE": "pdfplumber"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=25).run()
        self.app.switch_page(DEMO_PAGE).run()

    def upload_normal(self):
        self.app.file_uploader[0].set_value(("合成论文.pdf", make_pdf(texts=CHINESE_PAGES), "application/pdf")).run()

    def test_results_and_teacher_review_are_separate_and_reset_on_input_change(self):
        self.upload_normal()
        self.app.button(key="run_format_check").click().run()
        self.assertEqual(len(self.app.exception), 0)
        report = self.app.session_state["format_report"]
        self.assertEqual([item.status for item in report.results], ["符合"] * 3)
        self.app.toggle(key="format_review_enabled").set_value(True).run()
        token = self.app.session_state["format_run_token"]
        prefix = f"format_review_{token}_abstract_presence"
        self.app.selectbox(key=prefix + "_status").set_value("无法判断").run()
        self.app.text_area(key=prefix + "_note").set_value("教师需结合原 PDF 再核对摘要范围。").run()
        self.app.button(key=prefix + "_save").click().run()
        self.assertEqual(self.app.session_state["format_reviews"]["abstract_presence"]["status"], "无法判断")
        self.assertEqual(self.app.session_state["format_report"].results[0].status, "符合")
        self.assertEqual(self.app.download_button(key="download_format_report").label, "下载格式检查与复核报告（JSON）")
        self.app.file_uploader[0].set_value(("另一篇.pdf", make_pdf(), "application/pdf")).run()
        self.assertNotIn("format_report", self.app.session_state)
        self.assertNotIn("format_reviews", self.app.session_state)

    def test_parse_failure_remains_checkable_as_unknown(self):
        self.app.file_uploader[0].set_value(("失败.pdf", b"not a pdf", "application/pdf")).run()
        self.assertFalse(self.app.button(key="run_format_check").disabled)
        self.app.button(key="run_format_check").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(all(item.status == "无法判断" for item in self.app.session_state["format_report"].results))

    def test_missing_rules_directory_returns_unknown(self):
        with tempfile.TemporaryDirectory() as name, patch("paper_assistant.format_rules.STANDARDS_DIRECTORY", Path(name)):
            self.app.run()
            self.upload_normal()
            self.app.button(key="run_format_check").click().run()
            self.assertEqual(len(self.app.exception), 0)
            report = self.app.session_state["format_report"]
            self.assertIsNone(report.standard_id)
            self.assertEqual(report.results[0].status, "无法判断")

    def test_invalid_import_does_not_fallback_to_demo(self):
        self.upload_normal()
        self.app.file_uploader(key="format_standard_import").set_value(("坏规范.json", b"{}", "application/json")).run()
        self.app.button(key="run_format_check").click().run()
        self.assertIsNone(self.app.session_state["format_report"].standard_id)
        self.assertTrue(all(item.status == "无法判断" for item in self.app.session_state["format_report"].results))
        self.assertEqual(len(self.app.exception), 0)

    def test_changing_rules_clears_old_results_even_when_version_unchanged(self):
        self.upload_normal()
        self.app.button(key="run_format_check").click().run()
        data = json.loads((PROJECT_ROOT / "format_rules" / "01_demo_structure.json").read_text(encoding="utf-8"))
        data["rules"][0]["enabled"] = False
        self.app.file_uploader(key="format_standard_import").set_value(("调整规范.json", json.dumps(data).encode(), "application/json")).run()
        self.assertNotIn("format_report", self.app.session_state)
        self.app.button(key="run_format_check").click().run()
        self.assertEqual(self.app.session_state["format_report"].results[0].status, "无法判断")

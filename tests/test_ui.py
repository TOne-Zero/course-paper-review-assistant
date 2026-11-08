"""使用 Streamlit AppTest 操作真实入口，验证关键交互与旧结果清理。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pdf_fixture import make_pdf
from paper_assistant.routes import DEMO_PAGE


APP = Path(__file__).resolve().parents[1] / "app.py"


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {
            "ANALYSIS_MODE": "mock", "MAX_PDF_MB": "20", "MAX_PDF_PAGES": "100",
            "MAX_TEXT_CHARACTERS": "200000",
            "MIN_PAGE_TEXT_CHARACTERS": "30", "MIN_DOCUMENT_TEXT_CHARACTERS": "50",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.app.switch_page(DEMO_PAGE).run()

    def assert_clean(self):
        self.assertEqual(len(self.app.exception), 0, list(self.app.exception))

    def test_empty_page_and_disabled_start(self):
        self.assert_clean()
        self.assertEqual(self.app.title[0].value, "结课论文评价助手")
        self.assertTrue(self.app.button(key="start_analysis").disabled)
        self.assertEqual(len(self.app.metric), 0)

    def test_demo_flow_and_rubric_switch_clear_previous_result(self):
        self.app.checkbox[0].check().run()
        self.app.button(key="start_analysis").click().run()
        self.assert_clean()
        self.assertEqual(len(self.app.metric), 3)
        self.assertTrue(any(item.label == "下载模拟报告（Markdown）" for item in self.app.download_button))
        self.assertIn("模拟参考总分", self.app.metric[0].label)
        self.app.selectbox[0].set_value("research_methods").run()
        self.assertEqual(len(self.app.metric), 0)
        self.app.button(key="start_analysis").click().run()
        self.assert_clean()
        self.assertEqual(self.app.session_state["analysis_run"].rubric.id, "research_methods")

    def test_uploaded_pdf_flow_and_replacement_clear_previous_result(self):
        self.app.file_uploader[0].set_value(("论文.pdf", make_pdf(), "application/pdf")).run()
        self.app.button(key="start_analysis").click().run()
        self.assert_clean()
        self.assertEqual(len(self.app.metric), 3)
        self.assertEqual(self.app.session_state["analysis_run"].document.source, "pdf")
        self.app.file_uploader[0].set_value(("另一篇.pdf", make_pdf(pages=2), "application/pdf")).run()
        self.assertEqual(len(self.app.metric), 0)
        self.app.file_uploader[0].set_value(None).run()
        self.assertTrue(self.app.button(key="start_analysis").disabled)

    def test_bad_pdf_shows_chinese_error_without_results(self):
        self.app.file_uploader[0].set_value(("错误.pdf", b"not a pdf", "application/pdf")).run()
        self.assert_clean()
        self.assertTrue(self.app.button(key="start_analysis").disabled)
        self.assertEqual(len(self.app.metric), 0)
        self.assertTrue(any("有效的 PDF" in item.value for item in self.app.error))

    def test_uploaded_file_shows_parsing_overview_before_scoring(self):
        from tests.test_pdf_parser import CHINESE_PAGES
        self.app.file_uploader[0].set_value(("合成中文.pdf", make_pdf(texts=CHINESE_PAGES), "application/pdf")).run()
        self.assert_clean()
        self.assertTrue(any("文档解析概况" in item.value for item in self.app.subheader))
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(len(self.app.code), 3)
        self.assertIn("题目", self.app.code[0].value)
        self.assertTrue(any("候选位置" in item.value for item in self.app.text))
        self.assertFalse(self.app.button(key="start_analysis").disabled)

    def test_image_only_pdf_shows_unknown_page_and_disables_scoring(self):
        self.app.file_uploader[0].set_value(("图像.pdf", make_pdf(blank=True, image_pages={1}), "application/pdf")).run()
        self.assert_clean()
        self.assertTrue(self.app.button(key="start_analysis").disabled)
        self.assertEqual(len(self.app.metric), 0)
        self.assertTrue(any("无法判断" in item.value for item in self.app.text))
        self.assertTrue(any("可用文字不足" in item.value for item in self.app.error))


if __name__ == "__main__":
    unittest.main()

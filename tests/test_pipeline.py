import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from paper_assistant.analysis_service import analyze_document, analyze_pdf
from paper_assistant.config import Settings, load_settings
from paper_assistant.demo import demo_document
from paper_assistant.model_client import MockModelClient, create_model_client
from paper_assistant.pdf_parser import parse_pdf
from paper_assistant.report_exporter import export_json, export_markdown
from paper_assistant.rubrics import load_rubrics
from paper_assistant.schemas import AssistantError
from paper_assistant.validator import validate_result
from tests.pdf_fixture import make_pdf


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings()
        cls.rubrics = load_rubrics()
        cls.document = demo_document()

    def test_pdf_to_validated_report_for_each_rubric(self):
        content = make_pdf(pages=2)
        for rubric in self.rubrics:
            with self.subTest(rubric=rubric.id):
                run = analyze_pdf(content, "测试论文.pdf", rubric, self.settings)
                data = json.loads(export_json(run.result))
                self.assertEqual(len(run.document.pages), 2)
                self.assertIn("Synthetic course paper page 2", run.document.pages[1].text)
                self.assertEqual(data["document"]["source"], "pdf")
                self.assertTrue(data["is_mock"])
                self.assertTrue(data["teacher_decision_required"])
                self.assertAlmostEqual(data["total_score"], sum(d["score"] for d in data["dimensions"]))
                self.assertEqual(data["max_total_score"], 100)
                report = export_markdown(run.result).decode("utf-8")
                self.assertIn("模拟报告", report)
                self.assertIn("教师", report)
                self.assertIn("原文摘录", report)
                self.assertIn("测试论文", report)

    def test_demo_is_explicitly_marked_in_results_and_exports(self):
        run = analyze_document(self.document, self.rubrics[0], self.settings)
        self.assertEqual(run.result.data["document"]["source"], "demo")
        self.assertIn("模拟输入", export_markdown(run.result).decode("utf-8"))
        self.assertIn("未评估论文质量", run.result.data["notice"])

    def test_invalid_or_empty_pdf_is_rejected(self):
        for content in (b"", b"this is not a pdf", b"%PDF-1.7\ninvalid"):
            with self.subTest(content=content), self.assertRaises(AssistantError):
                parse_pdf(content, "bad.pdf", self.settings)

    def test_blank_pdf_keeps_unknown_page_and_blocks_analysis(self):
        document = parse_pdf(make_pdf(blank=True), "blank.pdf", self.settings)
        self.assertEqual(document.pages[0].status, "无法判断")
        self.assertFalse(document.can_analyze)
        self.assertIn("OCR", " ".join(document.warnings))
        with self.assertRaisesRegex(AssistantError, "无法判断"):
            analyze_document(document, self.rubrics[0], self.settings)

    def test_encrypted_pdf_is_rejected(self):
        with self.assertRaisesRegex(AssistantError, "加密"):
            parse_pdf(make_pdf(encrypted=True), "encrypted.pdf", self.settings)

    def test_file_page_and_text_limits_are_enforced(self):
        cases = [
            (b"%PDF-" + b"x" * (1024 * 1024), replace(self.settings, max_pdf_mb=1), "MB"),
            (make_pdf(pages=2), replace(self.settings, max_pdf_pages=1), "页"),
            (make_pdf(), replace(self.settings, max_text_characters=5), "字符"),
        ]
        for content, settings, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(AssistantError, message):
                parse_pdf(content, "limit.pdf", settings)

    def test_real_mode_fails_without_fallback_or_network(self):
        with self.assertRaisesRegex(AssistantError, "尚未配置"):
            create_model_client(replace(self.settings, mode="real"))

    def test_bad_environment_configuration_is_actionable(self):
        with patch.dict("os.environ", {"MAX_PDF_MB": "zero"}):
            with self.assertRaisesRegex(AssistantError, "MAX_PDF_MB"):
                load_settings()

    def test_invalid_rubric_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            data = {"id": "bad", "name": "错误标准", "version": "1", "description": "测试", "dimensions": [
                {"id": "one", "name": "一", "max_score": 20, "description": "不足百分"},
            ]}
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(AssistantError, "评分标准"):
                load_rubrics(Path(directory))

    def test_untrustworthy_model_responses_are_rejected(self):
        rubric = self.rubrics[0]
        original = MockModelClient().evaluate(self.document, rubric)
        cases = {}

        def changed(label, mutation):
            payload = copy.deepcopy(original)
            mutation(payload)
            cases[label] = payload

        changed("over_max", lambda p: p["dimensions"][0].update(score=999))
        changed("negative", lambda p: p["dimensions"][0].update(score=-1))
        changed("nan", lambda p: p["dimensions"][0].update(score=float("nan")))
        changed("boolean_score", lambda p: p["dimensions"][0].update(score=True))
        changed("total_mismatch", lambda p: p.update(total_score=1))
        changed("missing_dimension", lambda p: p["dimensions"].pop())
        changed("duplicate_dimension", lambda p: p["dimensions"].__setitem__(1, p["dimensions"][0]))
        changed("invented_quote", lambda p: p["dimensions"][0]["evidence"][0].update(quote="不存在的虚构证据"))
        changed("missing_page", lambda p: p["dimensions"][0]["evidence"][0].update(page=999))
        changed("boolean_page", lambda p: p["dimensions"][0]["evidence"][0].update(page=True))
        changed("wrong_document", lambda p: p["document"].update(sha256="wrong"))
        changed("wrong_rubric", lambda p: p["rubric"].update(version="99"))
        changed("no_mock_flag", lambda p: p.update(is_mock=False))
        changed("removed_notice", lambda p: p.pop("notice"))
        changed("removed_teacher_review", lambda p: p.update(teacher_decision_required=False))
        changed("missing_suggestions", lambda p: p["dimensions"][0].update(suggestions=[]))
        for label, payload in cases.items():
            with self.subTest(label=label), self.assertRaises(AssistantError):
                validate_result(payload, self.document, rubric)

    def test_export_escapes_untrusted_filename(self):
        document = replace(self.document, filename="<script>alert(1)</script>[点此](https://invalid.example)")
        run = analyze_document(document, self.rubrics[0], self.settings)
        report = export_markdown(run.result).decode("utf-8")
        self.assertNotIn("<script>", report)
        self.assertNotIn("[点此](", report)


if __name__ == "__main__":
    unittest.main()

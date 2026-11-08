import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from paper_assistant.config import PROJECT_ROOT, Settings
from paper_assistant.format_checker import check_format
from paper_assistant.format_rules import load_format_standard, parse_format_standard
from paper_assistant.pdf_parser import parse_pdf
from paper_assistant.schemas import AssistantError
from tests.pdf_fixture import make_pdf
from tests.test_pdf_parser import CHINESE_PAGES


STANDARD_PATH = PROJECT_ROOT / "format_rules" / "01_demo_structure.json"


class FormatCheckerTests(unittest.TestCase):
    def setUp(self):
        self.standard = load_format_standard(STANDARD_PATH)
        self.document = parse_pdf(make_pdf(texts=CHINESE_PAGES), "合成论文.pdf", Settings())

    def test_clear_sections_have_page_evidence_and_rule_basis(self):
        report = check_format(self.document, self.standard)
        self.assertEqual([item.status for item in report.results], ["符合"] * 3)
        for item in report.results:
            self.assertTrue(item.rule_source and item.rule_version and item.rule_scope and item.method)
            self.assertTrue(item.evidence)
            for evidence in item.evidence:
                page = self.document.pages[evidence.page - 1]
                original = "\n".join(page.raw_text.splitlines()[evidence.start_line - 1:evidence.end_line])
                self.assertIn(evidence.quote, original)

    def test_absent_label_is_only_suspected_with_search_scope_not_fabricated_quote(self):
        pages = CHINESE_PAGES.copy()
        pages[0] = pages[0].replace("关键词：课堂讨论；合成样例；文字解析", "")
        document = parse_pdf(make_pdf(texts=pages), "无关键词.pdf", Settings())
        item = next(item for item in check_format(document, self.standard).results if item.rule_id == "keywords_presence")
        self.assertEqual(item.status, "疑似不符合")
        self.assertTrue(item.checked_pages)
        self.assertFalse(item.evidence)
        self.assertIn("不是确认缺失", item.reason)

    def test_scan_and_blank_pages_do_not_become_format_errors(self):
        for content in (make_pdf(blank=True), make_pdf(blank=True, image_pages={1})):
            document = parse_pdf(content, "合成扫描.pdf", Settings())
            self.assertTrue(all(item.status == "无法判断" for item in check_format(document, self.standard).results))

    def test_entire_parse_failure_keeps_each_rule_unknown(self):
        with self.assertRaises(AssistantError):
            parse_pdf(b"not pdf", "bad.pdf", Settings())
        report = check_format(None, self.standard, parse_error="PDF 解析失败。")
        self.assertEqual(len(report.results), 3)
        self.assertTrue(all(item.status == "无法判断" and not item.evidence for item in report.results))

    def test_one_failed_page_prevents_absence_being_an_error(self):
        document = parse_pdf(make_pdf(pages=2, broken_pages={2}), "单页损坏.pdf", Settings())
        report = check_format(document, self.standard)
        self.assertTrue(all(item.status == "无法判断" for item in report.results))
        self.assertTrue(all(2 in item.uncertain_pages for item in report.results))

    def test_real_synthetic_table_detection_is_conservative(self):
        document = parse_pdf(make_pdf(pages=1, table_pages={1}), "合成表格.pdf", Settings())
        self.assertGreater(document.pages[0].table_count, 0)
        self.assertTrue(all(item.status == "无法判断" for item in check_format(document, self.standard).results))

    def test_table_cell_label_does_not_count_as_confirmed_section(self):
        pages = tuple(replace(page, table_count=2) for page in self.document.pages)
        document = replace(self.document, pages=pages)
        self.assertTrue(all(item.status == "无法判断" for item in check_format(document, self.standard).results))

    def test_layout_inspection_failure_does_not_become_format_error(self):
        with patch("paper_assistant.pdf_text_backend.PdfTextBackend.inspect_layout", return_value=(None, "检测未完成")):
            document = parse_pdf(make_pdf(), "版式检测失败.pdf", Settings())
        self.assertTrue(all(item.status == "无法判断" for item in check_format(document, self.standard).results))

    def test_directory_and_narrative_mentions_are_not_positive_evidence(self):
        document = parse_pdf(make_pdf(texts=[
            "目录\n摘要 ........ 1\n关键词 ........ 1\n参考文献 ........ 3\n这是用于检验目录排除的合成说明，不含真实学生信息。",
            "本文讨论摘要、关键词和参考文献等词语的检索方式，但没有把它们作为独立章节。\n本段是普通正文，不能因为提及这些词语就认定存在相应章节。",
        ]), "目录与提及.pdf", Settings())
        self.assertTrue(all(item.status != "符合" for item in check_format(document, self.standard).results))

    def test_only_labels_without_content_are_unknown(self):
        document = parse_pdf(make_pdf(texts=[
            "这是一段足够长的合成说明，用于保证整个页面可以提取文字，但不提供后面三个标签的任何内容。\n摘要\n关键词\n参考文献",
        ]), "空标签.pdf", Settings())
        self.assertTrue(all(item.status == "无法判断" for item in check_format(document, self.standard).results))

    def test_label_followed_by_number_or_another_label_is_not_a_pass(self):
        for suffix in ("摘要\n1\n问题重述", "摘要：关键词："):
            document = parse_pdf(make_pdf(texts=[
                "这是一段用于控制测试的合成文字，不包含真实学生论文。该样例专门检查空摘要标题之后的编号和其它标签。\n" + suffix,
            ]), "编号与标签.pdf", Settings())
            with self.subTest(suffix=suffix):
                self.assertEqual(check_format(document, self.standard).results[0].status, "无法判断")

    def test_missing_standard_file_does_not_invent_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AssistantError) as error:
                load_format_standard(Path(directory) / "missing.json")
        report = check_format(self.document, None, standard_error=str(error.exception))
        self.assertTrue(report.results)
        self.assertEqual(report.results[0].status, "无法判断")
        self.assertIsNone(report.standard_id)

    def test_empty_rule_list_is_not_vacuously_passed(self):
        data = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
        data["rules"] = []
        report = check_format(self.document, parse_format_standard(json.dumps(data).encode()))
        self.assertEqual([item.status for item in report.results], ["无法判断"])

    def test_missing_required_rule_fields_are_rejected(self):
        original = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
        for field in ("name", "source", "version", "scope", "method", "requirement"):
            data = copy.deepcopy(original)
            data["rules"][0].pop(field)
            with self.subTest(field=field), self.assertRaises(AssistantError):
                parse_format_standard(json.dumps(data).encode())
        data = copy.deepcopy(original)
        data.pop("rules")
        with self.assertRaises(AssistantError):
            parse_format_standard(json.dumps(data).encode())

    def test_unimplemented_method_and_disabled_rule_are_unknown(self):
        rule = replace(self.standard.rules[0], method="font_size", parameters={"size": 12})
        standard = replace(self.standard, rules=(rule, replace(self.standard.rules[1], enabled=False)))
        report = check_format(self.document, standard)
        self.assertTrue(all(item.status == "无法判断" for item in report.results))

    def test_new_config_source_and_version_are_used_without_hardcoding(self):
        data = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
        data["version"] = "2.2"
        data["source"] = "教师提供的本地测试说明（非认证）"
        data["rules"][0]["version"] = "2.2"
        data["rules"][0]["source"] = "本地测试说明第十条"
        standard = parse_format_standard(json.dumps(data).encode())
        report = check_format(self.document, standard)
        self.assertEqual(report.standard_version, "2.2")
        self.assertEqual(report.results[0].rule_source, "本地测试说明第十条")
        self.assertEqual(report.results[0].rule_version, "2.2")

    def test_pdf_geometry_is_observation_only(self):
        page = self.document.pages[0]
        self.assertAlmostEqual(page.width_mm, 595 / 72 * 25.4, places=2)
        self.assertAlmostEqual(page.height_mm, 842 / 72 * 25.4, places=2)
        self.assertEqual(page.rotation, 0)
        # 未配置尺寸规则，因此不会由尺寸推断全篇版式合格或不合格。
        self.assertEqual(len(check_format(self.document, self.standard).results), 3)

"""合成小 PDF 验证中文、章节候选、图像页与异常；不使用学生论文。"""

import json
import unittest
from dataclasses import replace

from paper_assistant.analysis_service import analyze_document
from paper_assistant.config import Settings
from paper_assistant.model_client import MockModelClient
from paper_assistant.pdf_parser import parse_pdf
from paper_assistant.report_exporter import export_json, export_markdown
from paper_assistant.rubrics import load_rubrics
from paper_assistant.schemas import AssistantError, PageText
from paper_assistant.section_locator import locate_sections
from paper_assistant.validator import validate_result
from tests.pdf_fixture import make_pdf


CHINESE_PAGES = [
    "题目：合成课堂讨论研究样例\n摘 要\n本文只使用虚构场景验证文字提取与章节候选位置，不包含任何真实学生信息或实际评价。\n关键词：课堂讨论；合成样例；文字解析",
    "一、引言\n本测试用于验证物理页码与提取文本行号。正文讨论完全由开发人员编写，不来源于任何学生论文。\n二、方法与讨论\n为便于人工核对，每页保留原始换行；此处没有真实实验结果。",
    "参考文献\n[1] 测试占位条目，仅用于检查章节位置，不是真实文献，不应作为引用来源。\n[2] 本测试不验证文献真实性，也不生成任何学术结论。",
]


class PdfParserTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()

    def test_real_chinese_pdf_extracts_pages_lines_and_candidate_locations(self):
        document = parse_pdf(make_pdf(texts=CHINESE_PAGES), "合成中文.pdf", self.settings)
        self.assertEqual([page.number for page in document.pages], [1, 2, 3])
        self.assertEqual(document.parsing_status, "可提取")
        self.assertIn("一、引言\n", document.pages[1].raw_text)
        sections = {section.name: section for section in document.sections}
        self.assertEqual(set(sections), {"标题", "摘要", "关键词", "正文", "参考文献"})
        self.assertTrue(all(section.status == "候选位置" for section in sections.values()))
        self.assertEqual(sections["摘要"].candidates[0].start_line, 2)
        self.assertEqual(sections["摘要"].candidates[0].end_line, 3)
        self.assertEqual(sections["正文"].candidates[0].start_page, 2)
        self.assertEqual(sections["正文"].candidates[0].end_page, 2)
        self.assertEqual(sections["参考文献"].candidates[0].start_page, 3)
        for section in sections.values():
            self.assertIn("可能误判", section.note)
            for span in section.candidates:
                lines = document.pages[span.start_page - 1].raw_text.splitlines()
                self.assertIn(lines[span.start_line - 1].strip(), span.excerpt)

    def test_english_headings_and_multiline_keywords(self):
        content = make_pdf(texts=[
            "Title: Synthetic parsing example\nAbstract\nThis is a synthetic abstract for testing the extraction workflow only.\nKeywords:\nparser; synthetic examples\n1 Introduction\nThe body is fictional and contains no student information.\nReferences\n[1] Synthetic placeholder, not a real reference."
        ])
        document = parse_pdf(content, "english.pdf", self.settings)
        sections = {section.name: section for section in document.sections}
        self.assertTrue(all(section.candidates for section in sections.values()))
        self.assertIn("parser; synthetic", sections["关键词"].candidates[0].excerpt)

    def test_blank_and_image_only_pages_remain_unknown(self):
        document = parse_pdf(make_pdf(texts=["", ""], image_pages={2}), "图像合成.pdf", self.settings)
        self.assertEqual([page.status for page in document.pages], ["无法判断", "无法判断"])
        self.assertFalse(document.pages[0].has_images)
        self.assertTrue(document.pages[1].has_images)
        self.assertIn("可能是扫描版", document.pages[1].reason)
        self.assertEqual(document.parsing_status, "无法判断")
        self.assertTrue(all(section.status == "无法判断" for section in document.sections))
        self.assertFalse(document.can_analyze)

    def test_too_little_text_is_retained_but_not_usable(self):
        document = parse_pdf(make_pdf(texts=["仅有两行\n123"]), "少量文字.pdf", self.settings)
        self.assertIn("仅有两行", document.pages[0].raw_text)
        self.assertIn("文字提取量过少", document.pages[0].reason)
        self.assertFalse(document.can_analyze)

    def test_document_threshold_can_block_otherwise_extractable_page(self):
        document = parse_pdf(make_pdf(), "短篇.pdf", replace(self.settings, min_document_text_characters=500))
        self.assertEqual(document.pages[0].status, "可提取")
        self.assertEqual(document.parsing_status, "无法判断")
        self.assertFalse(document.can_analyze)

    def test_one_unsupported_page_does_not_discard_other_pages(self):
        document = parse_pdf(make_pdf(pages=3, broken_pages={2}), "单页异常.pdf", self.settings)
        self.assertEqual([page.status for page in document.pages], ["可提取", "无法判断", "可提取"])
        self.assertIn("提取失败", document.pages[1].reason)
        self.assertEqual(document.parsing_status, "部分可提取")
        self.assertIn("page 3", document.pages[2].text)

    def test_obvious_garbled_encoding_is_unknown(self):
        document = parse_pdf(make_pdf(texts=["\ufffd" * 40 + "乱码测试"]), "乱码.pdf", self.settings)
        self.assertEqual(document.pages[0].status, "无法判断")
        self.assertIn("乱码", document.pages[0].reason)

    def test_unknown_pages_never_supply_evidence_and_reports_keep_warnings(self):
        document = parse_pdf(make_pdf(texts=[CHINESE_PAGES[0], "少量文字"]), "混合.pdf", self.settings)
        rubric = load_rubrics()[0]
        run = analyze_document(document, rubric, self.settings)
        data = json.loads(export_json(run.result))
        self.assertEqual(data["document"]["parsing"]["unknown_pages"], [2])
        self.assertIn("部分可提取", export_markdown(run.result).decode("utf-8"))
        self.assertIn("第 2 页", export_markdown(run.result).decode("utf-8"))
        self.assertTrue(all(e["page"] == 1 for d in data["dimensions"] for e in d["evidence"]))
        payload = MockModelClient().evaluate(document, rubric)
        payload["dimensions"][0]["evidence"][0].update(page=2, quote="少量文字")
        with self.assertRaises(AssistantError):
            validate_result(payload, document, rubric)

    def test_json_roundtrip_model_response_is_valid(self):
        document = parse_pdf(make_pdf(texts=CHINESE_PAGES), "测试.pdf", self.settings)
        rubric = load_rubrics()[0]
        payload = json.loads(json.dumps(MockModelClient().evaluate(document, rubric), ensure_ascii=False))
        self.assertIsNotNone(validate_result(payload, document, rubric))

    def test_missing_headings_are_unknown_not_claimed_absent(self):
        document = parse_pdf(make_pdf(), "无章节.pdf", self.settings)
        for section in document.sections:
            if section.name != "标题":
                self.assertEqual(section.status, "无法判断")
                self.assertIn("不代表论文缺少", section.note)

    def test_table_of_contents_is_not_used_as_actual_section(self):
        toc = "目录\n摘要 ........ 1\n引言 ........ 2\n参考文献 ........ 3"
        document = parse_pdf(make_pdf(texts=[toc, CHINESE_PAGES[1]]), "目录.pdf", self.settings)
        sections = {section.name: section for section in document.sections}
        self.assertEqual(sections["参考文献"].status, "无法判断")
        self.assertEqual(sections["标题"].status, "无法判断")
        self.assertEqual(sections["正文"].candidates[0].start_page, 2)

    def test_candidate_range_does_not_cross_unknown_page(self):
        pages = (
            PageText(1, "引言 正文开始", raw_text="引言\n正文开始"),
            PageText(2, "", status="无法判断"),
            PageText(3, "后续内容", raw_text="后续内容"),
        )
        body = next(section for section in locate_sections(pages) if section.name == "正文")
        self.assertEqual(body.candidates[0].end_page, 1)

    def test_zero_page_document_is_rejected(self):
        with self.assertRaisesRegex(AssistantError, "没有可读取的页面"):
            parse_pdf(make_pdf(pages=0), "零页.pdf", self.settings)


if __name__ == "__main__":
    unittest.main()

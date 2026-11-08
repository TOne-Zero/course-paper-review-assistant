"""不把用户授权论文加入仓库；使用合成编号章节覆盖实际遇到的结构。"""

import unittest
from dataclasses import replace

from paper_assistant.config import Settings
from paper_assistant.document_exporter import extract_section_text
from paper_assistant.pdf_parser import parse_pdf
from tests.pdf_fixture import make_pdf


class BodyExtractionTests(unittest.TestCase):
    def test_numbered_chapters_without_introduction_cover_whole_body(self):
        pages = [
            "题目：合成测试文章\n摘要\n本样例没有任何真实学生数据，专门验证无需引言标题的编号论文结构。\n关键词：合成；提取",
            "1 问题重述\n这是正文第一部分，包含研究背景和研究问题，不应因没有引言标题而遗漏。\n2 数据处理\n继续说明输入数据的检查方法与处理规则。\n1",
            "3 分析与讨论\n这是正文后半部分，算法应保留此处的文字，不能只提取第一节。\n4 结论\n结论末句应当保留，而且不能把页码当作正文内容。\n2",
            "参考文献\n[1] 这是用于测试的占位条目，不是真实参考文献。\nAI 工具使用声明\n声明内容不属于正文，也不属于参考文献条目。",
        ]
        for engine in ("pdfplumber", "pypdf"):
            with self.subTest(engine=engine):
                document = parse_pdf(make_pdf(texts=pages), "合成.pdf", replace(Settings(), pdf_text_engine=engine))
                section = next(item for item in document.sections if item.name == "正文")
                self.assertEqual((section.candidates[0].start_page, section.candidates[-1].end_page), (2, 3))
                body = extract_section_text(document)
                self.assertIn("结论末句", body)
                self.assertNotIn("参考文献", body)
                self.assertNotIn("AI 工具使用声明", body)
                self.assertNotIn("\n1\n", body)
                references = extract_section_text(document, "参考文献")
                self.assertNotIn("声明内容", references)

    def test_split_chapter_number_is_supported(self):
        document = parse_pdf(make_pdf(texts=[
            "题目：合成章节换行测试\n摘要\n此处是足够长的合成摘要，只用于检验真实文字提取和章节边界规则。\n关键词：测试",
            "1\n问题重述\n这是一段合成正文，不包含真实个人信息。章节数字与标题文字被排在不同的文本行。\n2\n研究方法\n这是方法段落，应一起进入正文候选。",
        ]), "换行.pdf", Settings())
        body = extract_section_text(document)
        self.assertIn("问题重述", body)
        self.assertIn("方法段落", body)

    def test_no_heading_uses_explicitly_uncertain_keywords_boundary(self):
        document = parse_pdf(make_pdf(texts=[
            "题目：没有编号标题的合成论文\n摘要\n合成摘要用于验证边界推断，不用于任何实际学术评价或学生评分。\n关键词：样例",
            "这里是没有章节标题的第一段合成正文，为了检验候选定位而编写了足够多的文字。\n随后继续讨论方法和局限，但不能把规则推断当作已经确认的完整正文。",
            "参考文献\n[1] 合成占位条目，用于测试后置材料边界，没有真实学术来源。",
        ]), "无标题.pdf", Settings())
        body = next(section for section in document.sections if section.name == "正文")
        self.assertIn("低把握", body.note)
        self.assertEqual(body.candidates[0].start_page, 2)

"""不包含真实学生资料的内置演示文本；不是 PDF 解析成功的替代证明。"""

import hashlib
import json

from paper_assistant.schemas import PageText, ParsedDocument
from paper_assistant.config import PROJECT_ROOT
from paper_assistant.pdf_parser import normalize_text
from paper_assistant.section_locator import locate_sections


def demo_document() -> ParsedDocument:
    source = json.loads((PROJECT_ROOT / "examples" / "demo_paper.json").read_text(encoding="utf-8"))
    pages = tuple(PageText(index, normalize_text("\n".join(paragraphs)), raw_text="\n".join(paragraphs))
                  for index, paragraphs in enumerate(source["pages"], 1))
    content = "\n".join(page.text for page in pages).encode("utf-8")
    return ParsedDocument(
        filename="内置演示文本（模拟输入）",
        sha256=hashlib.sha256(content).hexdigest(),
        pages=pages,
        source="demo",
        sections=locate_sections(pages),
        warnings=("当前使用内置演示文本，未上传或解析 PDF。",),
    )

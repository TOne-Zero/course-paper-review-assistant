"""仅导出解析结果；正文使用已定位的候选范围，不需要运行模拟评分。"""

import json
from dataclasses import asdict

from paper_assistant.schemas import ParsedDocument, document_metadata


def extract_section_text(document: ParsedDocument, name: str = "正文") -> str:
    section = next((item for item in document.sections if item.name == name), None)
    if section is None or not section.candidates:
        return ""
    pages = {page.number: page for page in document.reliable_pages}
    chunks = []
    seen = set()
    for span in section.candidates:
        for number in range(span.start_page, span.end_page + 1):
            page = pages.get(number)
            if page is None:
                continue
            lines = (page.raw_text or page.text).splitlines()
            start = span.start_line - 1 if number == span.start_page else 0
            end = span.end_line if number == span.end_page else len(lines)
            selected = []
            for index in range(start, end):
                if (number, index) in seen:
                    continue
                seen.add((number, index))
                line = lines[index]
                if line.strip().isdigit() and all(not item.strip() for item in lines[index + 1:]):
                    continue
                selected.append(line)
            if selected:
                chunks.append(f"【物理第 {number} 页】\n" + "\n".join(selected).strip())
    return "\n\n".join(chunks)


def export_parsed_document(document: ParsedDocument) -> bytes:
    return json.dumps({
        "document": document_metadata(document),
        "pages": [asdict(page) for page in document.pages],
        "body_text": extract_section_text(document),
        "notice": "正文为候选提取；复杂表格、公式、图片及阅读顺序仍需核对。",
    }, ensure_ascii=False, indent=2).encode("utf-8")

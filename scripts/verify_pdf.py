"""显式传入经授权的 PDF 后验证正文范围，结果默认写入忽略目录。"""

import argparse
import json
import time
from pathlib import Path

from paper_assistant.config import load_settings
from paper_assistant.document_exporter import export_parsed_document, extract_section_text
from paper_assistant.pdf_parser import parse_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="本地验证经授权的 PDF 正文候选")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--expect-start", type=int)
    parser.add_argument("--expect-end", type=int)
    parser.add_argument("--output", type=Path, default=Path(".runtime/pdf-validation"))
    args = parser.parse_args()
    started = time.perf_counter()
    document = parse_pdf(args.pdf.read_bytes(), args.pdf.name, load_settings())
    body = next(section for section in document.sections if section.name == "正文")
    if not body.candidates:
        raise SystemExit("没有可用的正文候选；无法判断。")
    start, end = body.candidates[0].start_page, body.candidates[-1].end_page
    if args.expect_start is not None and args.expect_start != start:
        raise SystemExit(f"正文起点不匹配：预期 {args.expect_start}，实际 {start}。")
    if args.expect_end is not None and args.expect_end != end:
        raise SystemExit(f"正文终点不匹配：预期 {args.expect_end}，实际 {end}。")
    text = extract_section_text(document)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "正文提取.txt").write_text(text, encoding="utf-8")
    (args.output / "逐页解析.json").write_bytes(export_parsed_document(document))
    summary = {
        "sha256": document.sha256, "pages": len(document.pages), "extractable_pages": len(document.reliable_pages),
        "body_start_page": start, "body_end_page": end, "body_characters": len(text),
        "engines": sorted({page.text_engine for page in document.pages}),
        "seconds": round(time.perf_counter() - started, 2),
        "notice": "范围核对不等于公式、表格、图像和所有字符均无损。",
    }
    (args.output / "验证概况.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

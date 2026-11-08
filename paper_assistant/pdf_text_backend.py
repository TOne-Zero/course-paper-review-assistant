"""调用开源文字提取器；不复制第三方实现。出处和许可见 OPEN_SOURCE.md。

pdfplumber: https://github.com/jsvine/pdfplumber (MIT), 基于 pdfminer.six (MIT)。
采用官方 dedupe_chars / extract_text 接口，根据字符坐标合并文字行。
pypdf 作为可配置的对照和异常回退，回退时向界面说明。
"""

from io import BytesIO
import re

import pdfplumber


class PdfTextBackend:
    def __init__(self, content: bytes, engine: str):
        self.engine = engine
        self.document = None
        self.warning = ""
        if engine == "pdfplumber":
            try:
                self.document = pdfplumber.open(BytesIO(content))
            except Exception:
                self.warning = "pdfplumber 无法打开文件，已回退到 pypdf；请核对提取内容。"

    def extract(self, page, index: int) -> tuple[str, str, str]:
        if self.document is not None:
            try:
                text = self.document.pages[index].dedupe_chars(tolerance=1).extract_text(
                    x_tolerance=2, y_tolerance=3,
                ) or ""
                if re.search(r"\(cid:\d+\)", text):
                    alternate = page.extract_text() or ""
                    if alternate.strip() and not re.search(r"\(cid:\d+\)", alternate):
                        return alternate, "pypdf", "pdfplumber 出现未映射字形编号，已用 pypdf 重新提取；请核对原文。"
                return text, "pdfplumber", ""
            except Exception:
                # 回退仍失败时由上层保留“无法判断”页。
                return page.extract_text() or "", "pypdf", "pdfplumber 本页提取失败，已回退到 pypdf。"
        return page.extract_text() or "", "pypdf", ""

    def close(self) -> None:
        if self.document is not None:
            self.document.close()

    def inspect_layout(self, index: int) -> tuple[int | None, str]:
        """开源启发式表格检测仅作保守排除，不认证版式正确。"""
        if self.document is None:
            return None, "当前提取器未完成表格与版式检查。"
        try:
            page = self.document.pages[index]
            if len(page.lines) + len(page.rects) + len(page.curves) > 500:
                return None, "页面图形对象较多，版式可能复杂，未自动排除表格风险。"
            count = len(page.find_tables())
            return count, "检测到表格，相关文字需人工核对。" if count else "启发式未检测到表格；不保证已排除所有复杂版式。"
        except Exception:
            return None, "表格与版式检测未完成，相关格式结论需人工核对。"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

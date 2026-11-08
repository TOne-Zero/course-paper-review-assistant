"""逐页提取文字、筛查异常与质量；失败页保留“无法判断”，不做 OCR。"""

import hashlib
import re
import math
import unicodedata
from io import BytesIO

from pypdf import PdfReader

from paper_assistant.config import Settings
from paper_assistant.pdf_text_backend import PdfTextBackend
from paper_assistant.schemas import AssistantError, PageText, ParsedDocument
from paper_assistant.section_locator import locate_sections


PARSER_VERSION = "3.1"


def _page_geometry(page) -> tuple[float | None, float | None, int | None]:
    """MediaBox 的物理尺寸，按 UserUnit 换算；不是正文页边距。"""
    try:
        unit = float(page.user_unit)
        width, height = float(page.mediabox.width) * unit * 25.4 / 72, float(page.mediabox.height) * unit * 25.4 / 72
        rotation = int(page.rotation)
        if not all(math.isfinite(value) and value > 0 for value in (unit, width, height)):
            return None, None, None
        return round(width, 2), round(height, 2), rotation if rotation in {0, 90, 180, 270} else None
    except Exception:
        return None, None, None


def normalize_text(text: str) -> str:
    """仅统一空白；供原文摘录核对，逐页查看使用保留换行的 raw_text。"""
    return " ".join(text.split())


def _contains_images(page) -> bool | None:
    """仅检查图像标记，不解码图像；不能据此断言页面一定是扫描件。"""
    try:
        return bool(page.images.keys())
    except Exception:
        return None


def _text_problem(raw_text: str, minimum: int) -> tuple[str, int]:
    meaningful = sum(character.isalnum() for character in raw_text)
    if not raw_text.strip():
        return "未提取到文字", meaningful
    if re.search(r"\(cid:\d+\)", raw_text):
        return "存在未映射的字体字形编号，无法可靠还原原文", meaningful
    visible = [character for character in raw_text if not character.isspace()]
    suspicious = sum(
        character == "\ufffd" or unicodedata.category(character) in {"Cc", "Co", "Cs", "Cn"}
        for character in visible
    )
    if visible and suspicious / len(visible) >= 0.1:
        return "提取文字含较多替代符、控制符或无法识别的编码，疑似乱码", meaningful
    if meaningful < minimum:
        return f"文字提取量过少（{meaningful} 个有效字符，低于 {minimum}）", meaningful
    return "", meaningful


def parse_pdf(content: bytes, filename: str, settings: Settings) -> ParsedDocument:
    if not content:
        raise AssistantError("文件为空，请重新上传 PDF。")
    if len(content) > settings.max_pdf_mb * 1024 * 1024:
        raise AssistantError(f"PDF 超过 {settings.max_pdf_mb} MB，请压缩或拆分后重试。")
    if not content.lstrip().startswith(b"%PDF-"):
        raise AssistantError("文件内容不是有效的 PDF，请确认文件格式。")

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise AssistantError("暂不支持加密 PDF，请先解除加密再上传。")
        count = len(reader.pages)
        if count == 0:
            raise AssistantError("PDF 没有可读取的页面。")
        if count > settings.max_pdf_pages:
            raise AssistantError(f"PDF 超过 {settings.max_pdf_pages} 页，请拆分后重试。")

    except AssistantError:
        raise
    except Exception:
        raise AssistantError("PDF 解析失败，文件可能已损坏或使用了暂不支持的编码。") from None

    pages = []
    warnings = []
    character_count = 0
    with PdfTextBackend(content, settings.pdf_text_engine) as backend:
        if backend.warning:
            warnings.append(backend.warning)
        for index in range(count):
            page_number = index + 1
            raw_text = ""
            has_images = None
            engine = settings.pdf_text_engine
            width = height = rotation = None
            table_count = None
            layout_note = "页面提取失败，版式信息无法可靠检查。"
            try:
                page = reader.pages[index]
                has_images = _contains_images(page)
                width, height, rotation = _page_geometry(page)
                raw_text, engine, backend_warning = backend.extract(page, index)
                raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
                table_count, layout_note = backend.inspect_layout(index)
                if backend_warning:
                    warnings.append(f"第 {page_number} 页：{backend_warning}")
                problem, meaningful = _text_problem(raw_text, settings.min_page_text_characters)
                if problem and has_images:
                    problem += "；检测到图像，可能是扫描版或图像为主的页面，当前不支持 OCR"
                elif problem and not raw_text.strip():
                    problem += "；可能为空白、矢量字形或扫描页面，当前不支持 OCR"
            except Exception:
                raw_text = ""
                meaningful = 0
                problem = "页面文字提取失败，可能使用不支持的内容或字体编码"

            text = normalize_text(raw_text)
            character_count += len(raw_text)
            if character_count > settings.max_text_characters:
                raise AssistantError(
                    f"提取文字超过 {settings.max_text_characters} 字符，请缩减文档后重试。"
                )
            if problem:
                warnings.append(f"第 {page_number} 页：无法判断。{problem}。")
            pages.append(PageText(
                number=page_number, text=text, raw_text=raw_text,
                status="无法判断" if problem else "可提取",
                reason=problem or "已提取文字；文字顺序、遗漏及版式仍需人工核对。",
                meaningful_characters=meaningful, has_images=has_images, text_engine=engine,
                width_mm=width, height_mm=height, rotation=rotation, table_count=table_count, layout_note=layout_note,
            ))

    usable_count = sum(page.meaningful_characters for page in pages if page.status == "可提取")
    sufficient = usable_count >= settings.min_document_text_characters
    if not sufficient:
        warnings.append(
            f"整篇可用文字过少（{usable_count} 个有效字符，低于 {settings.min_document_text_characters}）。"
            "文档解析结论：无法判断，已禁用评分分析；可逐页核对文本，或先用 OCR 生成可搜索 PDF。"
        )
    elif any(page.status == "无法判断" for page in pages):
        warnings.append("存在无法判断的页面，当前仅部分可提取；这些页不会作为评分摘录来源，不能据此评价完整论文。")

    return ParsedDocument(
        filename=filename, sha256=hashlib.sha256(content).hexdigest(),
        pages=tuple(pages), warnings=tuple(warnings),
        sections=locate_sections(tuple(pages)) if sufficient else locate_sections(()),
        sufficient_text=sufficient, parser_version=PARSER_VERSION,
    )

"""基于可观察证据的格式检查。不会扣分，也不将提取失败等同于违规。"""

import re
from datetime import datetime, timezone

from paper_assistant.format_schemas import FormatCheckReport, FormatEvidence, FormatRule, FormatRuleResult, FormatStandard
from paper_assistant.schemas import PageText, ParsedDocument
from paper_assistant.section_locator import BACKMATTER, NUMBERED_HEADING, PATTERNS, PREFIX


ENGINE_VERSION = "1.0"
LIMITATIONS = (
    "“符合”仅表示本条演示规则的标签和非空文本已检出，不代表整篇论文格式合格。",
    "“疑似不符合”仅表示在本次已检查范围未检出，不等于确认缺失；不自动扣分。",
    "扫描、图像、表格、提取失败或版式检测未完成可使结果为“无法判断”，不能据此判格式错误。",
    "不检查字体、字号、页边距、行距、复杂表格、引文样式、文献真实性或内容质量；PDF 尺寸仅是媒体框信息。",
    "表格与标题识别均为启发式，不能保证排除所有多栏或复杂版式，结果需教师结合原 PDF 复核。",
)
LABELS = {"摘要": r"摘\s*要|内容提要|abstract", "关键词": r"关\s*键\s*词|key\s*words?", "参考文献": r"参\s*考\s*文\s*献|references|bibliography"}
MATCHERS = {
    name: re.compile(rf"^\s*{PREFIX}(?:{label})(?:\s*[:：]\s*(?P<inline>.*)|\s+(?P<spaced>.+))?\s*$", re.I)
    for name, label in LABELS.items()
}


def _risk(page: PageText, *, absence: bool = False) -> str:
    if page.status != "可提取" or not (page.raw_text or page.text).strip():
        return "文字无法可靠提取"
    if page.table_count is None:
        return "表格或复杂版式尚未排除"
    if page.table_count > 0:
        return "检测到表格，不能将表格中的标签当作章节，也不能把遗漏当成格式错误"
    if absence and page.has_images is not False:
        return "存在图像或图像检测不明确，不能排除图像中的未提取文字"
    return ""


def _toc(page: PageText) -> bool:
    return any(re.fullmatch(r"\s*(?:目\s*录|contents|table of contents)\s*", line, re.I)
               for line in (page.raw_text or page.text).splitlines())


def _meaningful(text: str) -> bool:
    # 单独编号、页码或标点不作为非空章节内容，避免“摘要\n1”假阳性。
    return any(character.isalpha() for character in text)


def _break(text: str, section: str) -> bool:
    if any(pattern.fullmatch(text) for pattern in MATCHERS.values()):
        return True
    if BACKMATTER.fullmatch(text) or PATTERNS["正文"].fullmatch(text):
        return True
    if re.fullmatch(r"(?:\d+(?:\.\d+)*[.、]?|问题重述|研究背景|研究方法|结论|讨论)", text):
        return True
    return section != "参考文献" and bool(NUMBERED_HEADING.fullmatch(text))


def _evidence(document: ParsedDocument, page_index: int, line_index: int, match, section: str) -> tuple[FormatEvidence, ...]:
    page = document.pages[page_index]
    lines = (page.raw_text or page.text).splitlines()
    inline = match.group("inline") or match.group("spaced") or ""
    if _meaningful(inline) and not _break(inline, section):
        return (FormatEvidence(page.number, line_index + 1, line_index + 1, lines[line_index][:400]),)
    if inline.strip():
        return ()
    # 最多看本页后续 8 行和下一连续可靠页；不把后面的章节当成内容。
    examined = 0
    for following_index in range(page_index, min(page_index + 2, len(document.pages))):
        following = document.pages[following_index]
        if _risk(following) or _toc(following):
            return ()
        following_lines = (following.raw_text or following.text).splitlines()
        start = line_index + 1 if following_index == page_index else 0
        for index in range(start, len(following_lines)):
            text = following_lines[index].strip()
            examined += 1
            if examined > 8 or (text and _break(text, section)):
                return ()
            if not text or (text.isdigit() and index == len(following_lines) - 1):
                continue
            if _meaningful(text):
                if following_index == page_index:
                    return (FormatEvidence(page.number, line_index + 1, index + 1, "\n".join(lines[line_index:index + 1])[:600]),)
                return (
                    FormatEvidence(page.number, line_index + 1, line_index + 1, lines[line_index][:400]),
                    FormatEvidence(following.number, index + 1, index + 1, following_lines[index][:400]),
                )
    return ()


def _result(rule: FormatRule, status: str, reason: str, **kwargs) -> FormatRuleResult:
    return FormatRuleResult(rule.id, rule.name, status, reason, rule.source, rule.version, rule.scope,
                            rule.method, rule.requirement, **kwargs)


def _check_presence(document: ParsedDocument, rule: FormatRule) -> FormatRuleResult:
    section = rule.parameters["section"]
    checked = tuple(page.number for page in document.pages if not _risk(page) and not _toc(page))
    uncertain = tuple(page.number for page in document.pages if _risk(page, absence=True))
    tentative = []
    for page_index, page in enumerate(document.pages):
        if _toc(page):
            continue
        lines = (page.raw_text or page.text).splitlines()
        for line_index, line in enumerate(lines):
            if re.search(r"\.{3,}|…{2,}", line):
                continue
            match = MATCHERS[section].fullmatch(line)
            if not match:
                continue
            tentative.append(FormatEvidence(page.number, line_index + 1, line_index + 1, line[:400]))
            if _risk(page):
                continue
            evidence = _evidence(document, page_index, line_index, match, section)
            if evidence:
                return _result(rule, "符合", f"检出{section}标签及非空内容；仅满足本条结构检出要求，其它页面或格式仍需复核。",
                               checked_pages=checked, uncertain_pages=uncertain, evidence=evidence)
    if tentative:
        return _result(rule, "无法判断", f"检出可能的{section}标签，但未能在可靠范围核实非空内容或排除表格影响，不能判为空缺。",
                       checked_pages=checked, uncertain_pages=uncertain, evidence=tuple(tentative[:3]))
    if uncertain or document.warnings or not checked:
        return _result(rule, "无法判断", f"本次未检出{section}，但存在解析、图像或版式不确定性，不能据此认定缺失。",
                       checked_pages=checked, uncertain_pages=uncertain)
    return _result(rule, "疑似不符合", f"在已检查的全文可提取文本中未检出{section}标签；这只是搜索结果，不是确认缺失，需人工查看原 PDF。",
                   checked_pages=checked)


def check_format(document: ParsedDocument | None, standard: FormatStandard | None, *, parse_error: str | None = None,
                 standard_error: str | None = None) -> FormatCheckReport:
    results = []
    if standard is None or standard_error or not standard.rules:
        if standard_error:
            reason = standard_error
        elif standard is None:
            reason = "未提供有效格式规范。"
        else:
            reason = "格式规范未配置规则，不能视作检查通过。"
        results.append(FormatRuleResult(
            "configuration_unavailable", "格式规范可用性", "无法判断", reason,
            standard.source if standard else "未提供有效规范，不补造规范依据。", standard.version if standard else "未提供",
            standard.scope if standard else "未确定", "configuration_check", "需先提供有效规范及至少一条检查规则。",
        ))
    else:
        valid_document = document is not None and document.source in {'pdf','docx','doc'} and document.can_analyze
        if document is not None and [page.number for page in document.pages] != list(range(1, len(document.pages) + 1)):
            valid_document = False
        for rule in standard.rules:
            if not rule.enabled:
                results.append(_result(rule, "无法判断", "此规则已禁用，未执行检查。"))
            elif parse_error or not valid_document:
                reason = parse_error or "没有可靠的 PDF 解析结果；内置演示文本不属于实际 PDF。"
                results.append(_result(rule, "无法判断", reason))
            elif rule.method != "section_presence":
                results.append(_result(rule, "无法判断", f"尚未实现规范指定的检查方法（{rule.method}），未执行替代检查。"))
            else:
                try:
                    results.append(_check_presence(document, rule))
                except Exception:
                    results.append(_result(rule, "无法判断", "本项检查未能可靠完成，未转为格式错误，请人工复核。"))
    return FormatCheckReport(
        document.sha256 if document else None, document.filename if document else None,
        standard.id if standard else None, standard.name if standard else None,
        standard.version if standard else None, standard.digest if standard else None,
        standard.is_demo if standard else None, tuple(results), LIMITATIONS,
    )

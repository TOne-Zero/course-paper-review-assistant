"""对开源解析器的行输出定位章节；项目边界规则见 OPEN_SOURCE.md。

正文支持编号章节与前后置边界，不要求必须有“引言”。结果仍为候选范围。
"""

import re
from dataclasses import dataclass

from paper_assistant.schemas import PageText, SectionLocation, TextSpan


SECTION_NOTE = "规则识别的候选范围，可能误判或遗漏；页码为物理页码，行号为提取文本行号，非页面坐标。"
NAMES = ("标题", "摘要", "关键词", "正文", "参考文献")
PREFIX = r"(?:第[一二三四五六七八九十\d]+[章节]\s*|[一二三四五六七八九十\d]+[、.．)）]\s*|\d+(?:\.\d+)*\s+)?"
PATTERNS = {
    "摘要": re.compile(r"^(?:摘\s*要|abstract)(?:\s*[:：]\s*.*|\s+.*)?$", re.I),
    "关键词": re.compile(r"^(?:关\s*键\s*词|key\s*words?)(?:\s*[:：]\s*.*|\s+.*)?$", re.I),
    "正文": re.compile(rf"^{PREFIX}(?:引\s*言|绪\s*论|正\s*文|introduction)(?:\s*[:：].*|\s+.*)?$", re.I),
    "参考文献": re.compile(rf"^{PREFIX}(?:参\s*考\s*文\s*献|references|bibliography)\s*[:：]?$", re.I),
}


@dataclass(frozen=True)
class _Line:
    page: int
    number: int
    text: str


BACKMATTER = re.compile(
    rf"^{PREFIX}(?:参\s*考\s*文\s*献|references|bibliography|附\s*录(?:\s*[A-Z一二三四五六七八九十\d])?|appendix(?:\s+[A-Z\d])?|致\s*谢|acknowledg(?:e)?ments?|AI\s*工具使用声明|人工智能(?:工具)?使用声明)\s*[:：]?$", re.I,
)
NUMBERED_HEADING = re.compile(
    r"^(?:\d+(?:[.．]\d+)*(?:[.．、]\s*|\s+|(?=[\u4e00-\u9fff]))|[一二三四五六七八九十]+[、.．]\s*|第[一二三四五六七八九十\d]+[章节]\s*)(\S.{0,65})$"
)


def _heading_text(lines: list[_Line], index: int) -> str:
    text = lines[index].text
    if re.fullmatch(r"\d+(?:\.\d+)*[.、]?|[一二三四五六七八九十]+[、.]", text):
        if index + 1 < len(lines) and lines[index].page == lines[index + 1].page:
            return text + " " + lines[index + 1].text
    return text


def _is_numbered_heading(text: str) -> bool:
    match = NUMBERED_HEADING.fullmatch(text)
    return bool(match and not re.search(r"[。；;=<>]|\.{3,}|…{2,}", match.group(1)))


def _body_bounds(lines: list[_Line], matches: dict[str, list[int]]) -> tuple[int | None, int, str]:
    # 只把前部摘要和关键词作为前置材料，避免正文中的同名小节改变起点。
    front = [index for name in ("摘要", "关键词") for index in matches[name] if lines[index].page <= 5]
    after = max(front, default=-1)
    explicit = [index for index in matches["正文"] if index > after]
    numbered = [index for index in range(after + 1, len(lines)) if _is_numbered_heading(_heading_text(lines, index))]
    # 若前置部分之后已有编号首节，其位置优先于后文出现的“引言”字样。
    starts = [(index, "依据编号章节起点与后置材料边界定位") for index in numbered]
    starts.extend((index, "依据引言/绪论等章节词与后置材料边界定位") for index in explicit)
    if starts:
        start, note = min(starts, key=lambda item: item[0])
    elif any(index >= after for index in matches["关键词"]):
        keyword = max(index for index in matches["关键词"] if index >= after)
        candidates = [i for i in range(keyword + 1, len(lines))
                      if len(lines[i].text) >= 30 and not BACKMATTER.fullmatch(lines[i].text)]
        if not candidates:
            return None, -1, ""
        start, note = candidates[0], "低把握候选：依据关键词后的首个长段落定位，需重点核对是否仍含前置材料"
    else:
        return None, -1, ""
    endings = [i for i in range(start + 1, len(lines)) if BACKMATTER.fullmatch(lines[i].text)]
    end = endings[0] - 1 if endings else len(lines) - 1
    if end <= start:
        return None, -1, ""
    return start, end, note + ("；未发现可靠后置边界，候选延伸至最后可用文本" if not endings else "")


def _spans(lines: list[_Line], start: int, end: int) -> list[TextSpan]:
    groups = []
    begin = start
    for index in range(start + 1, end + 2):
        if index == end + 1 or lines[index].page > lines[index - 1].page + 1:
            first, last = lines[begin], lines[index - 1]
            excerpt = "\n".join(line.text for line in lines[begin:min(index, begin + 4)])[:240]
            groups.append(TextSpan(first.page, first.number, last.page, last.number, excerpt))
            begin = index
    return groups


def locate_sections(pages: tuple[PageText, ...]) -> tuple[SectionLocation, ...]:
    # 不跨越失败页合并段落；目录页不作正文锚点。
    lines = []
    for page in pages:
        if page.status != "可提取":
            continue
        page_lines = (page.raw_text or page.text).splitlines()
        if any(re.fullmatch(r"\s*(?:目\s*录|contents|table of contents)\s*", line, re.I) for line in page_lines):
            continue
        for number, text in enumerate(page_lines, 1):
            if not text.strip():
                continue
            # 只剔除页尾独占一行的数字页码，保留页首拆行的章节编号。
            if text.strip().isdigit() and all(not rest.strip() for rest in page_lines[number:]):
                continue
            lines.append(_Line(page.number, number, text.strip()))
    matches: dict[str, list[int]] = {name: [] for name in NAMES}
    for index, line in enumerate(lines):
        for name, pattern in PATTERNS.items():
            heading = _heading_text(lines, index)
            if len(heading) <= 160 and not re.search(r"\.{3,}|…{2,}", heading) and pattern.fullmatch(heading):
                matches[name].append(index)

    # 只从物理第一页的前 8 条非空行取标题候选，避免把下一页正文当作标题。
    first_lines = [(i, line) for i, line in enumerate(lines) if line.page == 1][:8]
    for index, line in first_lines:
        explicit = re.match(r"^(?:论文题目|题目|标题|title)\s*[:：]\s*(.+)$", line.text, re.I)
        if explicit and 2 <= len(explicit.group(1)) <= 120:
            matches["标题"] = [index]
            break
        if (
            6 <= len(line.text) <= 100
            and not re.search(r"[。！？!?；;]", line.text)
            and not re.match(r"^(?:课程|结课|本科|毕业|学年|姓名|学号|学院|班级|作者|教师|指导|日期|大学|本文|本研究|©|copyright|page\b)", line.text, re.I)
            and not re.fullmatch(r"[\d\s.\-/]+", line.text)
            and not any(pattern.fullmatch(line.text) for pattern in PATTERNS.values())
        ):
            matches["标题"] = [index]
            break

    body_start, body_end, body_note = _body_bounds(lines, matches)
    matches["正文"] = [body_start] if body_start is not None else []
    all_anchors = sorted({index for values in matches.values() for index in values})
    result = []
    for name in NAMES:
        candidates = []
        for index in matches[name]:
            end = index
            if name == "正文":
                end = body_end
            elif name not in {"标题", "关键词"}:
                following = [anchor for anchor in all_anchors if anchor > index]
                boundary = following[0] if following else len(lines)
                end = max(index, boundary - 1)
                if name == "参考文献":
                    stops = [i for i in range(index + 1, end + 1) if BACKMATTER.fullmatch(lines[i].text)]
                    if stops:
                        end = stops[0] - 1
            elif name == "关键词" and re.fullmatch(r"(?:关\s*键\s*词|key\s*words?)\s*[:：]?", lines[index].text, re.I):
                if index + 1 < len(lines) and index + 1 not in all_anchors and lines[index + 1].page == lines[index].page:
                    end = index + 1
            candidates.extend(_spans(lines, index, end))
        result.append(SectionLocation(
            name=name, status="候选位置" if candidates else "无法判断",
            candidates=tuple(candidates),
            note=(SECTION_NOTE + (" " + body_note if name == "正文" else "")) if candidates else "未找到可靠的规则锚点；不代表论文缺少该部分。",
        ))
    return tuple(result)

"""各模块共享的数据契约；不依赖 Streamlit。"""

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_WEIGHT_NOTE = "维度分值与分档界限为教学演示设置，需任课教师确认，不代表经验证的评分量表。"


class AssistantError(ValueError):
    """可以直接向用户展示的业务错误，不包含底层异常或密钥。"""


@dataclass(frozen=True)
class PageText:
    number: int  # PDF 物理页码，从 1 开始。
    text: str
    raw_text: str = ""  # 保留换行，章节行号以此字段为准。
    status: str = "可提取"  # 可提取 / 无法判断；不等同于全文正确。
    reason: str = ""
    meaningful_characters: int = 0
    has_images: bool | None = None
    text_engine: str = "pypdf"
    width_mm: float | None = None
    height_mm: float | None = None
    rotation: int | None = None
    table_count: int | None = None
    layout_note: str = "尚未检查表格与复杂版式。"


@dataclass(frozen=True)
class TextSpan:
    start_page: int
    start_line: int
    end_page: int
    end_line: int
    excerpt: str


@dataclass(frozen=True)
class SectionLocation:
    name: str
    status: str  # 候选位置 / 无法判断
    candidates: tuple[TextSpan, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    sha256: str
    pages: tuple[PageText, ...]
    warnings: tuple[str, ...] = ()
    source: str = "pdf"  # pdf / docx / doc / demo；Word页码来自本机转换版PDF。
    sections: tuple[SectionLocation, ...] = ()
    sufficient_text: bool = True
    parser_version: str = "3.0"

    @property
    def character_count(self) -> int:
        return sum(len(page.text) for page in self.pages)

    @property
    def reliable_pages(self) -> tuple[PageText, ...]:
        return tuple(page for page in self.pages if page.status == "可提取" and page.text)

    @property
    def can_analyze(self) -> bool:
        return self.sufficient_text and bool(self.reliable_pages)

    @property
    def parsing_status(self) -> str:
        if not self.can_analyze:
            return "无法判断"
        return "部分可提取" if len(self.reliable_pages) < len(self.pages) else "可提取"


def document_metadata(document: ParsedDocument) -> dict[str, Any]:
    """由解析器提供的来源信息，不能由模型改写；报告保留解析缺口提示。"""
    return {
        "filename": document.filename,
        "sha256": document.sha256,
        "page_count": len(document.pages),
        "character_count": document.character_count,
        "source": document.source,
        "parsing": {
            "parser_version": document.parser_version,
            "text_engines": sorted({page.text_engine for page in document.pages}),
            "status": document.parsing_status,
            "reliable_page_count": len(document.reliable_pages),
            "unknown_pages": [page.number for page in document.pages if page.status == "无法判断"],
            "warnings": list(document.warnings),
            "sections": [{
                "name": section.name, "status": section.status, "note": section.note,
                "candidates": [asdict(span) for span in section.candidates],
            } for section in document.sections],
        },
    }


@dataclass(frozen=True)
class ScoreBand:
    label: str
    min_ratio: float
    max_ratio: float
    description: str


@dataclass(frozen=True)
class RubricReference:
    id: str
    citation: str
    url: str
    note: str


@dataclass(frozen=True)
class RubricDimension:
    id: str
    name: str
    max_score: float
    description: str
    checklist: tuple[str, ...] = ()
    score_bands: tuple[ScoreBand, ...] = ()
    reference_ids: tuple[str, ...] = ()
    required: bool = True
    checklist_scores: tuple[float, ...] = ()


@dataclass(frozen=True)
class Rubric:
    id: str
    name: str
    version: str
    description: str
    dimensions: tuple[RubricDimension, ...]
    is_demo: bool = True
    schema_version: str = "2.0"
    weight_note: str = DEFAULT_WEIGHT_NOTE
    references: tuple[RubricReference, ...] = ()

    @property
    def total_score(self) -> float:
        return round(sum(item.max_score for item in self.dimensions), 2)


@dataclass(frozen=True)
class ValidatedResult:
    """仅由结果校验模块构造；data 是已校验的 JSON 可序列化副本。"""

    data: dict[str, Any]


@dataclass(frozen=True)
class AnalysisRun:
    document: ParsedDocument
    rubric: Rubric
    result: ValidatedResult

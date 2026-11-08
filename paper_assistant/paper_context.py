"""保留页码和字符区间的分段；完整覆盖可用页面，超限明确失败。"""

from dataclasses import asdict, dataclass

from paper_assistant.config import Settings
from paper_assistant.schemas import AssistantError, ParsedDocument, Rubric


@dataclass(frozen=True)
class PaperChunk:
    id: str
    page: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class EvaluationPlan:
    chunks: tuple[PaperChunk, ...]
    batches: tuple[tuple[PaperChunk, ...], ...]
    planned_calls: int
    coverage: dict


def plan_evaluation(document: ParsedDocument, rubric: Rubric, settings: Settings) -> EvaluationPlan:
    if not document.can_analyze:
        raise AssistantError("可用文字不足，无法判断；请先核对解析概况。")
    if not 1 <= settings.model_chunk_characters <= settings.model_batch_characters <= 32000:
        raise AssistantError("分段配置无效：需 1 ≤ 片段字符数 ≤ 批次字符数 ≤ 32000。")
    chunks = []
    for page in document.reliable_pages:
        for index, start in enumerate(range(0, len(page.text), settings.model_chunk_characters), 1):
            end = min(start + settings.model_chunk_characters, len(page.text))
            chunks.append(PaperChunk(f"p{page.number:03d}-c{index:03d}", page.number, start, end, page.text[start:end]))
    batches = []
    current, length = [], 0
    for chunk in chunks:
        if current and length + len(chunk.text) > settings.model_batch_characters:
            batches.append(tuple(current))
            current, length = [], 0
        current.append(chunk)
        length += len(chunk.text)
    if current:
        batches.append(tuple(current))
    calls = len(rubric.dimensions) + (len(batches) if len(batches) > 1 else 0)
    if calls > settings.model_max_calls:
        raise AssistantError(f"预计需要 {calls} 次模型请求，超过配置上限 {settings.model_max_calls}；未发送论文，也未截断内容。请调整分段预算或缩小待评价文件。")
    coverage = {
        "strategy": "full_text" if len(batches) == 1 else "all_chunks_then_evidence_synthesis",
        "page_numbers": [page.number for page in document.reliable_pages],
        "excluded_pages": [{"page": page.number, "reason": page.reason} for page in document.pages if page not in document.reliable_pages],
        "chunk_count": len(chunks), "batch_count": len(batches), "planned_calls": calls,
        "processed_chunk_ids": [], "actual_calls": 0,
        "input_characters": sum(len(chunk.text) for chunk in chunks),
        "chunk_manifest": [{"id": chunk.id, "page": chunk.page, "start": chunk.start, "end": chunk.end} for chunk in chunks],
        "note": "片段完整覆盖可用页的规范化文字；不可可靠提取的页列为缺口，不视为已评。长文先逐批抽取证据，最终评分仅使用抽取记录，可能遗漏语义，需教师核对。",
    }
    return EvaluationPlan(tuple(chunks), tuple(batches), calls, coverage)


def ranked_chunks(chunks: tuple[PaperChunk, ...], dimension) -> list[dict]:
    """相关性只调整展示顺序，不删除任何片段。"""
    terms = [dimension.name] + list(dimension.checklist)
    words = [word for term in terms for word in term.replace("、", " ").split() if len(word) > 1]
    return [asdict(chunk) for chunk in sorted(chunks, key=lambda item: -sum(word in item.text for word in words))]

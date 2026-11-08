"""结果元数据与合计由程序建立，模型只负责逐维度候选判断。"""

from datetime import datetime, timezone
from uuid import uuid4

from paper_assistant.rubrics import rubric_to_dict
from paper_assistant.schemas import document_metadata


MOCK_NOTICE = "模拟数据：分数为固定比例的演示值，未评估论文质量；建议为通用演示内容。原文摘录仅演示引用，不代表支持相应维度得分。教师最终决定成绩。"
REAL_NOTICE = "AI辅助评价，最终成绩由教师确定。程序只核验引用文字与页码是否存在，不核实评价观点是否正确；不判定抄袭、研究真实性或最终成绩。"


def total_score(dimensions: list[dict]) -> float | None:
    # 可选维度缺分也不默认为零；当前完整总分需要所有维度都有参考分。
    if any(item["score"] is None for item in dimensions):
        return None
    return round(sum(item["score"] for item in dimensions), 2)


def unscored(dimension, reason: str, code: str = "UNSCORABLE") -> dict:
    item = {"dimension_id": dimension.id, "name": dimension.name, "score": None, "max_score": dimension.max_score,
            "required": dimension.required, "status": "unscorable", "reason": reason, "evidence": [],
            "suggestions": ["请教师核对本维度材料、解析结果和课程要求后补充评价。"],
            "needs_teacher_review": True, "error_code": code,
            "evidence_status": "no_verified_evidence", "opinion_status": "未由程序核实的参考意见"}
    if dimension.checklist_scores:
        item['check_scores'] = [{'index': index + 1, 'text': text, 'max_score': maximum, 'score': None, 'reason': reason}
                                for index, (text, maximum) in enumerate(zip(dimension.checklist, dimension.checklist_scores))]
    return item


def build_result(document, rubric, *, mode: str, model: dict, dimensions: list[dict], coverage: dict,
                 course_requirements: str = "", diagnostics: list[str] | None = None) -> dict:
    return {
        "schema_version": "2.0", "mode": mode, "is_mock": mode == "mock",
        "evaluation_id": uuid4().hex,
        "notice": MOCK_NOTICE if mode == "mock" else REAL_NOTICE,
        "generated_at": datetime.now(timezone.utc).isoformat(), "document": document_metadata(document),
        "rubric": {"id": rubric.id, "name": rubric.name, "version": rubric.version},
        "rubric_snapshot": rubric_to_dict(rubric), "course_requirements": course_requirements,
        "model": model, "dimensions": dimensions, "total_score": total_score(dimensions),
        "max_total_score": rubric.total_score, "teacher_decision_required": True,
        "summary": "【模拟总结】流程演示结果，不能作为实际成绩。" if mode == "mock" else "AI辅助评价已完成；未评分项需教师补充，所有判断需人工复核。",
        "coverage": coverage, "diagnostics": diagnostics or [],
    }

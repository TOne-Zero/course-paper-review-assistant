"""教师分数/意见追加记录；不覆盖 AI 初评，空分绝不计为零。"""

import copy
import math
from datetime import datetime, timezone

from paper_assistant.evaluation_contract import total_score
from paper_assistant.schemas import AssistantError


def effective_dimensions(result, history: list[dict]) -> list[dict]:
    if any(event.get("evaluation_id") != result.data["evaluation_id"] for event in history):
        raise AssistantError("教师修改记录不属于本次评价，未合并到报告。")
    items = copy.deepcopy(result.data["dimensions"])
    latest = {event["dimension_id"]: event for event in history}
    for item in items:
        event = latest.get(item["dimension_id"])
        if event:
            item["score"] = event["new_score"]
            item["teacher_opinion"] = event["new_opinion"]
            item["reviewed"] = True
            if item.get('check_scores'):
                item['check_scores_notice'] = '小项分数保留AI初评；教师只调整本维度总分，未反推小项分数。'
        else:
            item["reviewed"] = False
    return items


def add_teacher_edit(result, history: list[dict], dimension_id: str, score: float | None, opinion: str, rationale: str) -> list[dict]:
    expected = {item["dimension_id"]: item for item in result.data["dimensions"]}
    if dimension_id not in expected:
        raise AssistantError("复核维度不存在。")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)
                              or not 0 <= score <= expected[dimension_id]["max_score"] or abs(score - round(score, 2)) > 1e-8):
        raise AssistantError("教师参考分必须在本维度范围内，最多两位小数；未评分请保留空分。")
    if not isinstance(opinion, str) or len(opinion) > 6000 or not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 6000:
        raise AssistantError("请填写复核依据；意见和依据各最多 6000 字符。")
    current = next(item for item in effective_dimensions(result, history) if item["dimension_id"] == dimension_id)
    event = {"sequence": len(history) + 1, "evaluation_id": result.data["evaluation_id"], "dimension_id": dimension_id, "previous_score": current["score"],
             "previous_opinion": current.get("teacher_opinion", ""), "new_score": score, "new_opinion": opinion.strip(),
             "rationale": rationale.strip(), "edited_at_utc": datetime.now(timezone.utc).isoformat(),
             "actor": "本地教师演示（无身份认证）", "opinion_status": "教师补充意见，未由程序核实"}
    return copy.deepcopy(history) + [event]


def review_summary(result, history: list[dict], confirmation: dict | None = None) -> dict:
    dimensions = effective_dimensions(result, history)
    total = total_score(dimensions)
    confirmed = bool(confirmation and confirmation.get("evaluation_id") == result.data["evaluation_id"]
                     and confirmation.get("history_length") == len(history) and total is not None)
    return {"dimensions": dimensions, "total_score": total,
            "total_label": "总分待教师确认" if total is None else f"{total:.2f}",
            "status": "教师已确认（本地演示，无身份认证）" if confirmed else "部分复核，尚未确认" if history else "未复核，尚未确认",
            "confirmed": confirmed}


def confirm_review(result, history: list[dict]) -> dict:
    if review_summary(result, history)["total_score"] is None:
        raise AssistantError("仍有未评分维度，总分待教师确认；请先补充分数，不能将缺失项计为零。")
    return {"evaluation_id": result.data["evaluation_id"], "history_length": len(history), "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
            "notice": "仅为本地教师确认记录，无身份认证，不向任何教务系统提交。"}

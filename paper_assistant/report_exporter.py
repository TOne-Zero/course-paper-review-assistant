"""导出已验证的 AI 初评、程序合计与独立教师修改记录。"""

import copy
import json
import re

from paper_assistant.schemas import AssistantError, ValidatedResult
from paper_assistant.teacher_review import review_summary


def safe_text(value: str) -> str:
    value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~\-])", r"\\\1", value)


def _score(value) -> str:
    return "未评分" if value is None else f"{value:.2f}"


def report_data(result: ValidatedResult, history=None, confirmation=None) -> dict:
    for item in result.data["dimensions"]:
        if any(evidence.get("verified") is not True for evidence in item["evidence"]):
            raise AssistantError("报告含未经校验的原文证据，已阻止导出。")
    data = copy.deepcopy(result.data)
    history = history or []
    review = review_summary(result, history, confirmation)
    data["teacher_review"] = dict(review, history=copy.deepcopy(history), confirmation=confirmation,
                                  notice="本地演示，无身份认证；人工意见未由程序核实，最终成绩由教师确定。")
    return data


def export_json(result: ValidatedResult, history=None, confirmation=None) -> bytes:
    return json.dumps(report_data(result, history, confirmation), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def export_markdown(result: ValidatedResult, history=None, confirmation=None) -> bytes:
    data = report_data(result, history, confirmation)
    document, rubric, review = data["document"], data["rubric"], data["teacher_review"]
    source_labels={'demo':'内置演示文本（模拟输入）','pdf':'上传的 PDF','docx':'上传的 Word（.docx，本机分页转换）','doc':'上传的 Word（.doc，本机分页转换）'}
    lines = ["# 结课论文评价助手 · " + ("模拟报告" if data["is_mock"] else "AI辅助评价报告"), "",
             "> AI辅助评价，最终成绩由教师确定。", "", safe_text(data["notice"]), "",
             f"- 文件：{safe_text(document['filename'])}",
             f"- 输入来源：{source_labels.get(document['source'],'上传的文档')}",
             f"- 文档 SHA-256：{document['sha256']}",
             f"- 评分标准：{safe_text(rubric['name'])}；版本：{safe_text(rubric['version'])}",
             f"- 模型：{safe_text(data['model']['name'])}；适配器：{safe_text(data['model']['provider'])}；服务：{safe_text(data['model']['service'])}",
             f"- 评价时间（UTC）：{safe_text(data['generated_at'])}",
             f"- AI初评合计：{_score(data['total_score']) if data['total_score'] is not None else '总分待教师确认'} / {data['max_total_score']:.2f}",
             f"- 复核后参考合计：{review['total_label']} / {data['max_total_score']:.2f}",
             f"- 人工复核状态：{safe_text(review['status'])}",
             "- 理由与建议均为参考意见，未由程序独立核实；引用文字存在不等于观点成立。", "",
             "## 本次课程要求", "", safe_text(data["course_requirements"] or "未补充，使用所选标准中的要求。"), "",
             "## 分项参考分", "", "| 维度 | AI初评 | 复核后参考分 | 满分 | 状态 |", "| --- | ---: | ---: | ---: | --- |"]
    for ai, current in zip(data["dimensions"], review["dimensions"]):
        lines.append(f"| {safe_text(ai['name'])} | {_score(ai['score'])} | {_score(current['score'])} | {ai['max_score']:.2f} | {'需教师复核' if ai['needs_teacher_review'] else '仍需教师决定成绩'} |")
    for item in data["dimensions"]:
        lines.extend(["", f"## {safe_text(item['name'])}", "", "AI评分理由（未由程序核实的参考意见）：", "", safe_text(item["reason"]), ""])
        if item.get('check_scores'):
            lines.extend(['### 细则初评分', '', '以下保留AI原始小项分数；教师改分独立记录在维度层级，不反推或覆盖AI小项。', '',
                          '| 检查细则 | AI初评 | 满分 | 评分理由 |', '| --- | ---: | ---: | --- |'])
            for check in item['check_scores']:
                lines.append(f"| {safe_text(check['text'])} | {_score(check['score'])} | {check['max_score']:.2f} | {safe_text(check['reason'])} |")
            lines.append('')
        if not item["evidence"]:
            lines.extend(["没有已验证的原文证据；本项不得作为已有证据支持的结论。", ""])
        for evidence in item["evidence"]:
            lines.extend([f"原文摘录 · 物理第 {evidence['page']} 页 · 片段 {safe_text(evidence['chunk_id'])}（程序已核对存在）：",
                          "", "> " + safe_text(evidence["quote"]), ""])
        lines.append("修改建议（参考意见，需人工核对）：")
        lines.extend("- " + safe_text(suggestion) for suggestion in item["suggestions"])
    lines.extend(["", "## 教师修改记录", "", "仅本地演示，不代表身份认证。教师补充意见未由程序核实。", ""])
    for event in review["history"]:
        lines.extend([f"- 第 {event['sequence']} 次 · {safe_text(event['dimension_id'])} · {safe_text(event['edited_at_utc'])}",
                      f"  分数：{_score(event['previous_score'])} → {_score(event['new_score'])}",
                      f"  原教师意见：{safe_text(event['previous_opinion'] or '无')}",
                      f"  新教师意见：{safe_text(event['new_opinion'] or '未补充')}",
                      f"  复核依据：{safe_text(event['rationale'])}"])
    if not review["history"]:
        lines.append("尚无教师修改记录。")
    lines.extend(["", "## 文档解析与处理范围", "", f"解析状态：{safe_text(document['parsing']['status'])}；页数：{document['page_count']}。", ""])
    lines.extend("- " + safe_text(warning) for warning in document["parsing"]["warnings"])
    coverage = data["coverage"]
    lines.extend([f"- 分段：{coverage['chunk_count']} 个片段，{coverage['batch_count']} 批；模型调用尝试 {coverage['actual_calls']} 次。",
                  "- " + safe_text(coverage["note"]),
                  "- 不能可靠提取的页不视作已评；章节定位、公式、表格、图像和阅读顺序仍需核对。"])
    for page in coverage["excluded_pages"]:
        lines.append(f"- 未用于评价：物理第 {page['page']} 页；{safe_text(page['reason'])}")
    for diagnostic in data["diagnostics"]:
        lines.append("- 调用/校验提示：" + safe_text(diagnostic))
    lines.extend(["", safe_text(data["summary"]), ""])
    return "\n".join(lines).encode("utf-8")

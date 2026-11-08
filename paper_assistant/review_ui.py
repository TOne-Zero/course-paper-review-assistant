"""逐维度展示参考分、验证证据、教师修改历史和导出。"""

import streamlit as st

from paper_assistant.report_exporter import export_json, export_markdown
from paper_assistant.schemas import AssistantError
from paper_assistant.teacher_review import add_teacher_edit, confirm_review, review_summary
from paper_assistant.presentation import render_document_note, render_evidence, render_review_state


def render_evaluation(run) -> None:
    data = run.result.data
    history = st.session_state.setdefault("teacher_history", [])
    confirmation = st.session_state.get("teacher_confirmation")
    summary = review_summary(run.result, history, confirmation)
    render_document_note(run.document)
    for diagnostic in data["diagnostics"]:
        st.error(diagnostic)
    with st.container(key="result_summary"):
        columns = st.columns([1.5, 1, 1])
        columns[0].metric("模拟参考总分" if data["is_mock"] else "AI参考总分",
                          "总分待教师确认" if data["total_score"] is None else f"{data['total_score']:.2f} / {data['max_total_score']:.0f}")
        columns[1].metric("论文页数", len(run.document.pages))
        columns[2].metric("提取字符数", run.document.character_count)
        render_review_state(summary)
    st.caption("引文已核对存在；评分观点与建议仍需教师判断。")
    st.dataframe([
        {"评分维度": ai["name"], "AI初评": ai["score"], "复核后参考分": current["score"], "满分": ai["max_score"],
         }
        for ai, current in zip(data["dimensions"], summary["dimensions"])
    ], hide_index=True, width="stretch")
    allow_review = st.toggle("教师复核与修改", key="evaluation_review_enabled")
    token = st.session_state["analysis_run_token"]
    for index, (ai, current) in enumerate(zip(data["dimensions"], summary["dimensions"])):
        with st.expander(f"{ai['name']} · {'未评分' if ai['score'] is None else format(ai['score'], '.2f')} / {ai['max_score']:.2f}", expanded=index == 0 or ai["score"] is None):
            evidence_area, opinion_area = st.columns([1.2, 1], gap="large")
            with evidence_area:
                st.markdown("**原文证据**")
                if not ai["evidence"]:
                    st.info("无已验证原文证据；该意见不能作为已有证据支持的结论。")
                for evidence in ai["evidence"]:
                    render_evidence(evidence)
            with opinion_area:
                st.markdown('<p class="review-opinion-title">参考意见</p>', unsafe_allow_html=True)
                st.text(ai["reason"])
                st.markdown("**修改建议**")
                for suggestion in ai["suggestions"]:
                    st.text("• " + suggestion)
            if allow_review:
                st.divider()
                st.markdown("**教师复核**")
                prefix = f"grade_review_{token}_{ai['dimension_id']}"
                score_area, comment_area = st.columns([1, 2], gap="large")
                with score_area:
                    score = st.number_input("教师参考分（留空表示未评分）", min_value=0.0, max_value=float(ai["max_score"]),
                                            value=None if current["score"] is None else float(current["score"]), step=0.5,
                                            format="%.2f", key=prefix + "_score")
                    st.caption(f"本维度满分 {ai['max_score']:g}；AI初评保持原样。")
                with comment_area:
                    opinion = st.text_area("教师意见", value=current.get("teacher_opinion", ""), key=prefix + "_opinion", height=100)
                rationale = st.text_area("修改或复核依据（必填）", key=prefix + "_rationale", height=88)
                if st.button("保存本维度修改", key=prefix + "_save"):
                    try:
                        st.session_state["teacher_history"] = add_teacher_edit(run.result, history, ai["dimension_id"], score, opinion, rationale)
                        st.session_state.pop("teacher_confirmation", None)
                        st.rerun()
                    except AssistantError as error:
                        st.error(str(error))
    if allow_review:
        st.caption("修改保留 AI 初评，仅记录本机复核，不提交教务系统。")
        acknowledge = st.checkbox("我已结合原文和课程要求复核全部维度", key=f"confirm_all_{token}")
        if st.button("确认本轮教师复核", key="confirm_evaluation_review"):
            if not acknowledge:
                st.error("请先确认已核对全部维度。")
            else:
                try:
                    st.session_state["teacher_confirmation"] = confirm_review(run.result, history)
                    st.rerun()
                except AssistantError as error:
                    st.error(str(error))
        with st.expander("查看教师修改历史"):
            for event in history:
                st.text(f"第 {event['sequence']} 次 · {event['dimension_id']} · {event['previous_score']} → {event['new_score']}")
                st.text(event["rationale"])
    with st.container(key="report_exports"):
        st.subheader("保存本次评阅")
        st.caption("含 AI 初评、教师修改和复核记录。")
        left, right = st.columns(2)
        left.download_button("下载模拟报告（Markdown）" if data["is_mock"] else "下载评价报告（Markdown）",
                             export_markdown(run.result, history, st.session_state.get("teacher_confirmation")),
                             file_name="论文评价报告.md", mime="text/markdown; charset=utf-8", key="download_evaluation_markdown", width="stretch")
        right.download_button("下载评价与修改记录（JSON）", export_json(run.result, history, st.session_state.get("teacher_confirmation")),
                              file_name="论文评价与修改记录.json", mime="application/json", key="download_evaluation_json", width="stretch")
    with st.expander("评价记录与版本", expanded=False):
        st.caption(data["notice"])
        st.caption(f"模型：{data['model']['name']}；评价时间（UTC）：{data['generated_at']}；评分标准版本：{run.rubric.version}")

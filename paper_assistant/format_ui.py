"""独立格式检查与本地教师复核界面，不参与自动评分。"""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st

from paper_assistant.format_checker import ENGINE_VERSION, LIMITATIONS, check_format
from paper_assistant.format_rules import list_format_standards, parse_format_standard
from paper_assistant.schemas import AssistantError, ParsedDocument


def render_format_panel(document: ParsedDocument | None, *, parse_error: str | None, has_input: bool, input_signature) -> None:
    st.subheader("格式检查（独立于评分）")
    st.caption("按所选规范检查，不自动扣分。解析失败标记“无法判断”。")
    entries = {}
    for path in list_format_standards():
        try:
            content = path.read_bytes()
            standard = parse_format_standard(content)
            entries[path.name] = (standard, None, content)
        except (AssistantError, OSError) as error:
            message = str(error) if isinstance(error, AssistantError) else "规范文件无法读取。"
            entries[path.name] = (None, message, b"")
    selection = st.selectbox(
        "格式规范", options=list(entries) or ["__missing__"], key="format_standard_choice",
        format_func=lambda value: (
            f"{entries[value][0].name} · {entries[value][0].version}" if value in entries and entries[value][0]
            else f"{value}（配置不可用）" if value in entries else "未找到规范文件"
        ), disabled=not entries,
    )
    standard, standard_error, content = entries.get(selection, (None, "没有格式规范文件；未自动生成规则，无法判断。", b""))
    with st.expander("导入其它格式规范", expanded=False):
        imported = st.file_uploader("导入格式规范（JSON，可选，最多 1 MB）", type=["json"], max_upload_size=1,
                                    key="format_standard_import" + st.session_state.get("upload_generation", ""))
    if imported is not None:
        content = imported.getvalue()
        st.caption("正在使用导入规范；若无效，不会回退到内置演示规则。导入内容仅在当前会话使用。")
        try:
            standard = parse_format_standard(content)
            standard_error = None
        except AssistantError as error:
            standard, standard_error = None, str(error)
    if standard is not None:
        if standard.is_demo:
            st.warning("内置参考规范，非高校官方标准。")
        else:
            st.info("此规范由配置提供者声明，本应用没有认证其学校来源或适用性；请教师先核对。")
        with st.expander("规范依据与检查范围", expanded=False):
            st.text(f"规范：{standard.name}；版本：{standard.version}")
            st.text(f"来源：{standard.source}")
            st.text(f"适用范围：{standard.scope}")
            for rule in standard.rules:
                st.text(f"{rule.name} · 版本 {rule.version} · {'启用' if rule.enabled else '禁用'}")
                st.caption(f"来源：{rule.source}；范围：{rule.scope}")
                st.text(rule.requirement)
                st.caption("检查方法：" + ("标题标签定位 + 非空文本证据核对" if rule.method == "section_presence" else f"尚未实现（{rule.method}）"))
        st.download_button("下载当前格式规范（JSON）", content, file_name="格式规范.json", mime="application/json", key="download_format_standard")
    if standard_error:
        st.error(standard_error)
    with st.expander("检查局限与判定含义", expanded=False):
        for limitation in LIMITATIONS:
            st.text(limitation)
    if document is not None and document.source == "pdf":
        with st.expander("PDF 可获取的信息（不作版式合格判定）"):
            st.caption("以下为 PDF 媒体框尺寸及旋转角，不是纸张印刷尺寸、正文页边距或字号。表格检测是启发式。")
            st.dataframe([
                {"物理页": page.number, "宽度 mm": page.width_mm, "高度 mm": page.height_mm,
                 "旋转角": page.rotation, "表格候选数": page.table_count, "版式提示": page.layout_note}
                for page in document.pages
            ], hide_index=True, width="stretch")
    signature = hashlib.sha256(repr((input_signature, selection, hashlib.sha256(content).hexdigest(), standard_error, ENGINE_VERSION)).encode("utf-8")).hexdigest()
    if st.session_state.get("format_input_signature") != signature:
        st.session_state["format_input_signature"] = signature
        st.session_state.pop("format_report", None)
        st.session_state.pop("format_reviews", None)
    if st.button("开始格式检查", key="run_format_check", disabled=not has_input):
        st.session_state["format_report"] = check_format(document, standard, parse_error=parse_error, standard_error=standard_error)
        st.session_state["format_reviews"] = {}
        st.session_state["format_run_token"] = uuid4().hex
        st.session_state["format_checked_at"] = datetime.now(timezone.utc).isoformat()
    report = st.session_state.get("format_report")
    if report is None:
        st.info("上传 PDF 后可检查。")
        return
    st.dataframe([
        {"规则": item.name, "系统结果": item.status, "证据物理页": "、".join(str(e.page) for e in item.evidence) or "未定位",
         "依据版本": item.rule_version, "说明": item.reason}
        for item in report.results
    ], hide_index=True, width="stretch")
    st.caption("仅列逐项结果，不生成格式总分或整篇合格结论。")
    allow_review = st.toggle("复核格式结果", key="format_review_enabled")
    reviews = st.session_state.setdefault("format_reviews", {})
    token = st.session_state["format_run_token"]
    for item in report.results:
        with st.expander(f"{item.name} · {item.status}", expanded=False):
            st.text(f"系统判断：{item.status}。{item.reason}")
            st.text(f"规范依据：{item.rule_source}；版本：{item.rule_version}")
            st.caption(f"适用范围：{item.rule_scope}")
            st.text(f"检查要求：{item.requirement}")
            st.caption("已检查物理页：" + ("、".join(map(str, item.checked_pages)) or "无可靠搜索范围"))
            if item.uncertain_pages:
                st.caption("存在不确定性的物理页：" + "、".join(map(str, item.uncertain_pages)))
            for evidence in item.evidence:
                st.caption(f"原文证据 · 物理第 {evidence.page} 页，提取文本第 {evidence.start_line}–{evidence.end_line} 行")
                st.text(evidence.quote)
            if not item.evidence:
                st.text("没有可定位的原文证据；“未检出”只作为搜索记录，不能定位为某页的格式错误。")
            if allow_review:
                prefix = f"format_review_{token}_{item.rule_id}"
                status = st.selectbox("教师复核结论", ["未复核", "符合", "疑似不符合", "无法判断"], key=prefix + "_status")
                note = st.text_area("复核说明（记录核对依据，不代表身份认证）", key=prefix + "_note")
                if st.button("保存本项复核", key=prefix + "_save"):
                    if status == "未复核":
                        reviews.pop(item.rule_id, None)
                        st.info("已清除此项复核记录。")
                    elif not note.strip():
                        st.error("请填写复核依据后保存。")
                    else:
                        reviews[item.rule_id] = {"status": status, "note": note.strip(), "reviewed_at_utc": datetime.now(timezone.utc).isoformat()}
                        st.success("已保存在当前会话，系统原始判断保持独立记录。")
            if item.rule_id in reviews:
                st.text(f"已保存教师复核：{reviews[item.rule_id]['status']}；{reviews[item.rule_id]['note']}")
    st.caption("复核保存在当前会话，请及时下载。")
    exported = {
        "schema_version": "1.0", "checked_at_utc": st.session_state["format_checked_at"],
        "automated_report": asdict(report), "teacher_reviews": reviews,
        "review_notice": "本地演示，无身份认证；教师复核与系统判断分别记录，不自动调整成绩。",
    }
    st.download_button("下载格式检查与复核报告（JSON）", json.dumps(exported, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name="格式检查与复核报告.json", mime="application/json", key="download_format_report")

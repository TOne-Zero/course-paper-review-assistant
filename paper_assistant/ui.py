"""中文界面：选择输入与评分标准、触发分析、展示证据与下载报告。"""

import hashlib
from pathlib import Path
from uuid import uuid4

import streamlit as st

from paper_assistant.analysis_service import analyze_document
from paper_assistant.api_transport import service_label, validate_api_settings
from paper_assistant.config import Settings, load_settings
from paper_assistant.demo import demo_document
from paper_assistant.document_exporter import export_parsed_document, extract_section_text
from paper_assistant.document_parser import PARSER_VERSION, parse_document
from paper_assistant.review_ui import render_evaluation
from paper_assistant.paper_context import plan_evaluation
from paper_assistant.privacy import clear_managed_files, configure_private_logging
from paper_assistant.rubrics import load_rubrics
from paper_assistant.rubric_editor import render_rubric_editor
from paper_assistant.format_ui import render_format_panel
from paper_assistant.schemas import AnalysisRun, AssistantError, ParsedDocument
from paper_assistant.presentation import render_header, render_document_note, render_empty_result, render_workflow
from paper_assistant.routes import SETTINGS_PAGE, render_entry_links
from paper_assistant.batch import (MAX_BATCH_FILES, activate_paper, analyze_batch, collect_uploads,
    evaluation_signature, export_batch, parse_batch, store_active, sync_batch)


def render_parsing_overview(document: ParsedDocument) -> None:
    st.subheader("文档解析概况")
    st.text(f"解析状态：{document.parsing_status}；总页数：{len(document.pages)}；"
            f"可提取页数：{len(document.reliable_pages)}；提取字符数：{document.character_count}")
    st.caption("“可提取”仅表示通过基础文字筛查，不保证全文完整或顺序正确。页码均为物理页码。")
    st.caption("文字提取：" + "、".join(sorted({page.text_engine for page in document.pages})) + "；开源出处见项目 OPEN_SOURCE.md。")
    for warning in document.warnings:
        st.warning(warning)
    if not document.can_analyze:
        st.error("可用文字不足：无法判断。请查看逐页文本；当前已禁用评分分析。")
    st.dataframe([
        {"页码": page.number, "状态": page.status, "提取字符数": len(page.text), "提取器": page.text_engine, "提示": page.reason}
        for page in document.pages
    ], hide_index=True, width="stretch")
    st.markdown("**章节候选位置（需要人工核对）**")
    st.caption("依据标题词和文本行规则识别，可能误判或遗漏；未识别不代表论文缺少该部分。范围不是页面坐标。")
    if document.source == "demo":
        st.info("当前为内置演示文本，未经过 PDF 解析，不能用于检验 PDF 解析效果。")
    for section in document.sections:
        st.text(f"{section.name}：{section.status}")
        for candidate in section.candidates:
            st.caption(f"候选：第 {candidate.start_page} 页第 {candidate.start_line} 行"
                       f"至第 {candidate.end_page} 页第 {candidate.end_line} 行（提取文本行号）")
            st.text(candidate.excerpt)
        st.caption(section.note)
    body = extract_section_text(document)
    if body:
        with st.expander("查看完整正文候选（按物理页分段）"):
            st.text(body)
        st.download_button("下载正文候选文本", body.encode("utf-8"), file_name="正文提取_候选.txt", mime="text/plain; charset=utf-8", key="download_body")
    st.download_button("下载逐页解析结果（JSON）", export_parsed_document(document), file_name="逐页解析结果.json", mime="application/json", key="download_parsed")
    with st.expander("逐页提取文本（含提取行号）"):
        for page in document.pages:
            st.markdown(f"**第 {page.number} 页 · {page.status}**")
            st.caption(page.reason)
            if page.raw_text or page.text:
                st.code(page.raw_text or page.text, language=None, line_numbers=True, wrap_lines=True)
            else:
                st.text("无法判断：本页没有可展示的提取文字。")


def render_result(run: AnalysisRun) -> None:
    render_evaluation(run)


def main(*, mode: str) -> None:
    if mode not in {"mock", "real"}:
        raise ValueError("Invalid workbench mode")
    configure_private_logging()
    render_header("正式评阅" if mode == "real" else "模拟运行")
    settings_problem = None
    try:
        settings = load_settings(mode=mode)
    except AssistantError as error:
        if mode == "mock":
            st.error(str(error))
            return
        settings = Settings(mode="real")
        settings_problem = str(error)
    try:
        rubrics = load_rubrics()
    except AssistantError as error:
        st.error(str(error))
        return

    with st.sidebar:
        st.header("评阅工作台")
        if mode == "mock":
            render_entry_links(demo=True)
        workflow_area = st.empty()
        st.divider()
        st.caption("结果仅保留在当前会话，请及时下载。")
    api_problem = None
    if settings.mode == "mock":
        st.markdown('<div class="mode-note" role="note"><strong>模拟模式</strong> · 使用演示分数和建议，不发送论文，不代表真实评价或最终成绩。</div>', unsafe_allow_html=True)
    else:
        try:
            if settings_problem:
                raise AssistantError(settings_problem)
            validate_api_settings(settings)
        except AssistantError as error:
            api_problem = str(error)
        if api_problem:
            with st.container(key="configuration_notice"):
                if st.button("正式评阅尚未就绪 · 点击配置模型服务", icon=":material/settings:", key="open_api_configuration", width="stretch"):
                    st.switch_page(SETTINGS_PAGE)
                if not api_problem.startswith("模型服务尚未配置"):
                    st.caption(api_problem)
    pending_tab = st.session_state.pop("pending_workspace_tab", None)
    if pending_tab is not None:
        st.session_state["workspace_tab"] = pending_tab
    preparation, evaluation, formatting = st.tabs(
        ["论文准备", "评价与复核", "格式检查"], key="workspace_tab", on_change="rerun",
    )
    with preparation:
        upload_area, course_area = st.columns([1.05, 1], gap="large")
        with upload_area, st.container(key="upload_panel"):
            st.subheader("论文文件")
            uploads = st.file_uploader(
                "上传 Word / PDF 论文", type=["pdf","docx","doc"], accept_multiple_files=mode == "real",
                max_upload_size=settings.max_pdf_mb, disabled=mode == "mock" and st.session_state.get("use_demo", False),
                help="支持Word与PDF混合多选；Word在本机分页转换后读取，扫描图片暂不支持OCR。上传解析不调用模型。",
                key="paper_pdf" + st.session_state.get("upload_generation", ""),
            )
            st.caption((f"每批 {MAX_BATCH_FILES} 篇 · 合计 50 MB · " if mode == "real" else "")
                       + f"单篇 {settings.max_pdf_mb} MB / {settings.max_pdf_pages} 页")
            use_demo = st.checkbox("使用内置演示文本（模拟输入，无需上传）", key="use_demo") if mode == "mock" else False
            batch_problem = None
            try:
                papers = collect_uploads(uploads) if not use_demo else []
            except AssistantError as error:
                papers, batch_problem = [], str(error)
                st.error(batch_problem)
            active_id = papers[0].key if papers else "demo" if use_demo else None
            if len(papers) > 1:
                if st.session_state.get("batch_selected") not in {paper.key for paper in papers}:
                    st.session_state.pop("batch_selected", None)
                pending = st.session_state.pop("pending_batch_selected", None)
                if pending in {paper.key for paper in papers}:
                    st.session_state["batch_selected"] = pending
                active_id = st.selectbox("当前论文", [paper.key for paper in papers], key="batch_selected",
                    format_func=lambda key: next(f"{i}. {paper.name}" for i, paper in enumerate(papers, 1) if paper.key == key))
            raw_files = uploads if isinstance(uploads, list) else [uploads] if uploads is not None else []
            uploaded = next((raw_files[i] for i, paper in enumerate(papers) if paper.key == active_id), None)
            demo_pdf = Path(__file__).resolve().parent.parent / "examples" / "演示论文_原创虚构.pdf"
            if mode == "mock" and demo_pdf.exists():
                st.download_button("下载原创演示论文（PDF）", demo_pdf.read_bytes(), file_name=demo_pdf.name,
                                   mime="application/pdf", key="download_demo_paper", width="stretch")
            document_area = st.empty()
        with course_area, st.container(key="course_panel"):
            st.subheader("本次评价要求")
            pending_rubric_id = st.session_state.pop("pending_rubric_id", None)
            if pending_rubric_id in {rubric.id for rubric in rubrics}:
                st.session_state["course_rubric"] = pending_rubric_id
            rubric_id = st.selectbox(
                "课程评分标准", options=[rubric.id for rubric in rubrics],
                format_func=lambda value: next(r.name for r in rubrics if r.id == value).replace("演示标准", "参考标准") if mode == "real" else next(r.name for r in rubrics if r.id == value), key="course_rubric",
            )
            rubric = next(r for r in rubrics if r.id == rubric_id)
            st.caption(f"版本 {rubric.version} · 满分 {rubric.total_score:.0f} · {len(rubric.dimensions)} 个评价维度")
            if rubric.is_demo:
                st.caption("当前为内置参考标准，不是任何高校的官方标准。" if mode == "real" else "当前为演示标准，不是任何高校的官方标准。")
            course_requirements = st.text_area(
                "课程要求（可选）", max_chars=6000, key="course_requirements",
                height=112, placeholder="例如：重点关注研究问题是否清楚、方法与结论是否对应。",
            )
            with st.expander("查看评分标准", expanded=False):
                render_rubric_details(rubric)
            with st.expander("管理课程标准", expanded=False):
                render_rubric_editor(rubric)
            if st.session_state.get("rubric_notice"):
                st.success(st.session_state.pop("rubric_notice"))
            action_area = st.container(key="start_action")

    context = evaluation_signature(None, rubric, course_requirements, settings)
    snapshots = sync_batch(st.session_state, [paper.key for paper in papers] or (["demo"] if use_demo else []), active_id, context)
    if papers:
        with preparation, st.spinner("正在读取论文……"):
            parse_batch(papers, snapshots, settings, parser=parse_document)
    activate_paper(st.session_state, snapshots.get(active_id, {}))
    content = uploaded.getvalue() if uploaded is not None and not use_demo else None
    parse_signature = (
        "demo" if use_demo else hashlib.sha256(content).hexdigest() if content is not None else "empty",
        uploaded.name if uploaded is not None and not use_demo else "demo" if use_demo else "",
        (settings.max_pdf_mb, settings.max_pdf_pages, settings.max_text_characters, settings.min_page_text_characters,
         settings.min_document_text_characters, settings.pdf_text_engine), PARSER_VERSION,
    )
    if st.session_state.get("parse_signature") != parse_signature:
        st.session_state["parse_signature"] = parse_signature
        st.session_state.pop("parsed_document", None)
        st.session_state.pop("parse_error", None)
        try:
            if use_demo or uploaded is not None:
                with st.spinner("正在解析论文……" if not use_demo else "正在加载内置演示文本……"):
                    st.session_state["parsed_document"] = (
                        demo_document() if use_demo else parse_document(content, uploaded.name, settings)
                    )
        except AssistantError as error:
            st.session_state["parse_error"] = str(error)
        except Exception:
            st.session_state["parse_error"] = "文档解析未完成，无法判断；请更换文件后重试。"

    signature = evaluation_signature(parse_signature, rubric, course_requirements, settings)
    # 切换论文或标准立即清除旧结果，避免把上一份结果误认为当前结果。
    if st.session_state.get("input_signature") != signature:
        st.session_state.pop("analysis_run", None)
        st.session_state.pop("teacher_history", None)
        st.session_state.pop("teacher_confirmation", None)
        st.session_state["input_signature"] = signature

    document = st.session_state.get("parsed_document")
    if st.session_state.get("parse_error"):
        with preparation:
            st.error(st.session_state["parse_error"])
    if document is not None:
        with document_area.container():
            render_document_note(document)
        with preparation:
            if not document.can_analyze:
                st.error("可用文字不足：无法判断。请查看逐页文本；当前已禁用评分分析。")
            elif document.warnings:
                st.warning("部分页面提取受限，请核对文本。")
            with st.expander("核对提取文本与章节", expanded=False):
                render_parsing_overview(document)

    plan_problem = None
    if document is not None and document.can_analyze:
        try:
            plan = plan_evaluation(document, rubric, settings)
            with action_area:
                if len(papers) <= 1:
                    st.caption(f"{len(plan.coverage['page_numbers'])} 页 · {len(plan.chunks)} 个片段 · "
                               + (f"最多 {plan.planned_calls} 次请求" if settings.mode == "real" else "不发起模型请求"))
                if plan.coverage["excluded_pages"]:
                    st.warning("存在未用于评价的解析缺口，不能视为已读完整论文；页码与原因会写入报告。")
        except AssistantError as error:
            plan_problem = str(error)
            with action_area:
                st.error(plan_problem)
    cloud_ack = False
    if settings.mode == "real" and papers and not api_problem:
        ack_key = hashlib.sha256(repr((tuple(paper.key for paper in papers), context)).encode("utf-8")).hexdigest()[:16]
        with action_area:
            cloud_ack = st.checkbox(f"允许将{'本批次 ' + str(len(papers)) + ' 篇' if len(papers) > 1 else '当前'}论文发送至 {service_label(settings)}",
                key="cloud_ack_" + ack_key, disabled=bool(api_problem) or not papers,
                help="发送可提取文字、物理页码、课程要求和评分标准。请先取得论文使用授权；上传解析和配置保存不调用模型。")
    with action_area:
        start_all = False
        batch_plan_errors = {}
        if len(papers) > 1:
            eligible = [paper for paper in papers if snapshots[paper.key].get("parsed_document") is not None
                        and snapshots[paper.key]["parsed_document"].can_analyze and not snapshots[paper.key].get("analysis_run")]
            planned_calls = 0
            for paper in eligible:
                try:
                    planned_calls += plan_evaluation(snapshots[paper.key]["parsed_document"], rubric, settings).planned_calls
                except AssistantError as error:
                    batch_plan_errors[paper.key] = str(error)
            st.caption(f"{len(eligible)-len(batch_plan_errors)} 篇待处理 · 预计最多 {planned_calls} 次请求")
            start_all = st.button("分析全部", key="start_batch", type="primary", width="stretch",
                disabled=len(eligible) == len(batch_plan_errors) or bool(api_problem) or (settings.mode == "real" and not cloud_ack))
        start = st.button("仅分析当前篇" if len(papers) > 1 else "开始分析", key="start_analysis", type="secondary" if len(papers) > 1 else "primary", width="stretch",
                          disabled=document is None or not document.can_analyze or bool(api_problem or plan_problem) or (settings.mode == "real" and not cloud_ack))
    if start_all:
        store_active(st.session_state)
        with preparation:
            progress = st.progress(0, text="开始批量分析")
            analyze_batch(papers, snapshots, rubric, settings, course_requirements, allow_cloud=cloud_ack,
                analyzer=analyze_document, progress=lambda index, total, name: progress.progress((index-1)/total, text=f"{index}/{total} · {name}"))
            progress.progress(1.0, text="本批次处理结束")
        activate_paper(st.session_state, snapshots.get(active_id, {}))
        results = [paper.key for paper in papers if snapshots[paper.key].get("analysis_run")]
        if results:
            st.session_state["pending_batch_selected"] = active_id if active_id in results else results[0]
            st.session_state["pending_workspace_tab"] = "评价与复核"
        st.rerun()
    if start:
        st.session_state.pop("analysis_run", None)
        st.session_state.pop("teacher_history", None)
        st.session_state.pop("teacher_confirmation", None)
        try:
            with action_area:
                status = st.empty()
                with st.spinner("正在逐项评价，请稍候……"):
                    run = analyze_document(document, rubric, settings, course_requirements=course_requirements,
                                           allow_cloud=cloud_ack, progress=lambda message: status.text(message))
                    st.session_state["analysis_run"] = run
                    st.session_state["analysis_run_token"] = uuid4().hex
                    st.session_state.pop("analysis_error", None)
                    store_active(st.session_state)
            status.empty()
            st.session_state["pending_workspace_tab"] = "评价与复核"
            st.rerun()
        except AssistantError as error:
            st.session_state["analysis_error"] = str(error)
            with action_area:
                st.error(str(error))
        except Exception:
            with action_area:
                st.error("分析暂未完成，请重新选择文件后重试；若仍失败，请联系项目维护同事检查。")

    run = st.session_state.get("analysis_run")
    with evaluation:
        if run is None:
            render_empty_result()
        else:
            st.subheader("本篇评价")
            render_result(run)
    with formatting:
        render_format_panel(document, parse_error=st.session_state.get("parse_error"), has_input=uploaded is not None or use_demo,
                            input_signature=parse_signature)
    store_active(st.session_state)
    if len(papers) > 1:
        with preparation:
            st.subheader("本批次")
            rows = []
            for paper in papers:
                snapshot = snapshots[paper.key]
                item_run = snapshot.get("analysis_run")
                item_doc = snapshot.get("parsed_document")
                reason = snapshot.get("analysis_error") or snapshot.get("parse_error") or batch_plan_errors.get(paper.key, "")
                status = ("已复核" if snapshot.get("teacher_confirmation") else "待复核") if item_run else "失败" if reason else "文字不足" if item_doc and not item_doc.can_analyze else "待分析"
                rows.append({"论文": paper.name, "状态": status, "页数": str(len(item_doc.pages)) if item_doc else "—", "提示": reason})
            st.dataframe(rows, hide_index=True, width="stretch")
            if any(snapshot.get("analysis_run") for snapshot in snapshots.values()):
                st.download_button("打包下载报告（ZIP）", export_batch(papers, snapshots), file_name="论文评阅报告.zip",
                    mime="application/zip", key="download_batch_reports", width="stretch")
    with workflow_area.container():
        render_workflow(document, run, bool(st.session_state.get("teacher_confirmation")))
    with st.sidebar:
        st.divider()
        with st.expander("会话与隐私", expanded=False):
            st.caption("本机使用，无身份认证。清理不删除已下载报告或服务商副本；暂不支持 OCR。")
            if st.session_state.get("cleanup_notice"):
                st.info(st.session_state.pop("cleanup_notice"))
            if st.button("清理当前会话与应用托管分析文件", key="clear_private_data", width="stretch"):
                outcome = clear_managed_files()
                st.session_state.clear()
                st.session_state["upload_generation"] = uuid4().hex
                st.session_state["cleanup_notice"] = f"当前会话已清理，删除应用托管文件 {outcome['deleted_files']} 个；{outcome['not_removed']} 个目标未能处理（权限或链接等原因）。"
                st.rerun()


def render_rubric_details(rubric) -> None:
    st.write(rubric.description)
    st.caption(f"标准版本：{rubric.version}；满分合计：{rubric.total_score:.0f} 分；配置格式：{rubric.schema_version}")
    st.info(rubric.weight_note)
    st.dataframe([
        {"维度": item.name, "满分": item.max_score, "评价要求": item.description}
        for item in rubric.dimensions
    ], hide_index=True, width="stretch")
    for dimension in rubric.dimensions:
        st.text(dimension.name + " · 需要检查：" + "；".join(dimension.checklist))
        for band in dimension.score_bands:
            st.text(f"{band.label}（{band.min_ratio * dimension.max_score:g}–{band.max_ratio * dimension.max_score:g} 分）：{band.description}")
        if dimension.reference_ids:
            st.caption("设计参考：" + "、".join(dimension.reference_ids) + "；具体检查项和分档为课程评价改编。")
    if rubric.references:
        st.markdown("**参考来源与适用范围**")
        st.caption("这些来源用于设计参考，不为课程权重背书；导入配置中的参考信息由配置提供者声明。")
        for source in rubric.references:
            st.text(f"{source.id} · {source.citation}")
            st.caption(source.note)
            st.link_button(f"查看 {source.id} 来源", source.url)

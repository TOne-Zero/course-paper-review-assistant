"""论文评阅界面的样式与安全的只读展示组件；不改变评价数据。"""

from html import escape

import streamlit as st

from paper_assistant import __version__


STYLES = """
<style>
:root {
  --paper: #F8F7F3;
  --sheet: #FFFFFF;
  --inset: #EEEFE9;
  --ink: #242D27;
  --muted-ink: #626961;
  --rule: #D9DDD4;
  --forest: #245C48;
  --forest-dark: #194433;
  --forest-wash: #E6EDE5;
  --annotation: #8F4C3F;
  --annotation-wash: #F4EAE3;
  --font-reading: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  --font-heading: "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", SimSun, serif;
}
.stApp { background: var(--paper); color: var(--ink); }
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button, .stApp select,
.stApp [data-testid="stText"] {
  font-family: var(--font-reading);
}
.stApp p, .stApp li { line-height: 1.75; }
.stApp h1, .stApp h2, .stApp h3 {
  color: var(--ink); font-family: var(--font-heading); font-weight: 600;
  letter-spacing: .01em; line-height: 1.4; text-wrap: balance;
}
.stApp h1 { font-size: 2rem; padding: 0; margin: 0 0 .5rem; }
.stApp h2 { font-size: 1.5rem; }
.stApp h3 { font-size: 1.2rem; padding-top: .25rem; }
.stApp [data-testid="stMainBlockContainer"] {
  max-width: 1440px; padding: 2.25rem 3rem 3rem;
}
.stApp [data-testid="stHeader"] { background: var(--paper); }
.stApp [data-testid="stSidebar"] { background: var(--paper); border-right: 1px solid var(--rule); }
.stApp [data-testid="stSidebarUserContent"] { padding: 2rem 1.25rem; }
.stApp [data-testid="stSidebar"] h2 { font-size: 1.35rem; }
.stApp [data-testid="stSidebar"] p { font-size: .875rem; }
.stApp [data-testid="stCaptionContainer"] { color: var(--muted-ink); font-size: .8125rem; opacity: 1; }
.stApp [data-testid="stCaptionContainer"] p { font-size: .8125rem; line-height: 1.65; }
.stApp [data-baseweb="tab-list"] {
  gap: 2rem; border-bottom: 1px solid var(--rule); margin-bottom: 1.75rem;
}
.stApp [data-baseweb="tab"] {
  padding: 1rem 0; height: auto; color: var(--muted-ink); background: transparent;
}
.stApp [data-baseweb="tab"] p { font-size: .9375rem; font-weight: 500; }
.stApp [data-baseweb="tab"][aria-selected="true"] { color: var(--forest); }
.stApp [data-baseweb="tab-highlight"] { background: var(--forest); height: 2px; }
.stApp [data-baseweb="tab-border"] { background: transparent; }
.stApp button { min-height: 2.75rem; transition: background-color 140ms ease-out, border-color 140ms ease-out; }
.stApp button[kind="primary"] { background: var(--forest); border-color: var(--forest); color: white; }
.stApp button[kind="primary"]:hover { background: var(--forest-dark); border-color: var(--forest-dark); }
.stApp button[kind="secondary"], .stApp [data-testid="stDownloadButton"] button {
  border-color: var(--rule); color: var(--ink); background: var(--sheet);
}
.stApp button[kind="secondary"]:hover, .stApp [data-testid="stDownloadButton"] button:hover {
  border-color: var(--forest); color: var(--forest); background: var(--forest-wash);
}
.stApp button:disabled { opacity: .55; cursor: not-allowed; }
.stApp button:focus-visible, .stApp a:focus-visible, .stApp summary:focus-visible {
  outline: 2px solid var(--forest); outline-offset: 3px;
}
.stApp input, .stApp textarea { caret-color: var(--forest); }
.stApp [data-baseweb="input"], .stApp [data-baseweb="textarea"],
.stApp [data-baseweb="select"] > div { background: var(--inset); border-color: var(--rule); }
.stApp input::placeholder, .stApp textarea::placeholder { color: var(--muted-ink); opacity: 1; }
.stApp [data-testid="stFileUploaderDropzone"] {
  background: var(--forest-wash); border: 1px dashed #829A86;
  border-radius: 12px; padding: 1.5rem 1rem; min-height: 10rem;
}
.stApp [data-testid="stFileUploaderDropzone"] button { background: var(--sheet); }
.stApp [data-testid="stExpander"] { border: 1px solid var(--rule); border-radius: 12px; background: transparent; }
.stApp [data-testid="stExpander"] > details { border: none; }
.stApp [data-testid="stExpander"] summary { padding: .75rem 1rem; }
.stApp [data-testid="stExpander"] summary p { color: var(--ink); font-weight: 500; }
.stApp [data-testid="stAlertContainer"] { border: 0; border-radius: 8px; }
.stApp [data-testid="stAlertContentError"] p { color: var(--annotation); }
.stApp [data-testid="stMetricLabel"] p { color: var(--muted-ink); font-size: .8125rem; }
.stApp [data-testid="stMetricValue"] { font-family: var(--font-heading); font-size: 1.75rem; color: var(--forest); }
.stApp [data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
.stApp [data-testid="stText"] { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.85; }
.stApp [data-testid="stCode"] { border-radius: 8px; }
.stApp hr { border-color: var(--rule); margin: 1.25rem 0; }
.st-key-upload_panel, .st-key-course_panel {
  background: var(--sheet); border-radius: 12px; padding: 1.25rem 1.5rem;
}
.st-key-start_action { margin-top: .5rem; }
.stApp .st-key-configuration_notice button {
  color: var(--annotation); background: var(--annotation-wash); border-color: var(--annotation);
  text-align: left; justify-content: flex-start;
}
.st-key-configuration_form { background: var(--sheet); padding: 1.25rem 1.5rem; border-radius: 12px; }
.st-key-header_settings { position: fixed; top: 3.5rem; right: 3rem; width: 44px; z-index: 50; }
.stApp .st-key-header_settings button { width: 44px; height: 44px; min-height: 44px; padding: 0; border: 1px solid var(--rule); background: var(--sheet); border-radius: 12px; }
.st-key-header_settings button p { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.st-key-provider_heading { padding-bottom: .5rem; border-bottom: 1px solid var(--rule); margin-bottom: .5rem; }
.provider-status { color: var(--muted-ink); font-size: .8125rem; }
.st-key-configuration_form [data-testid="stForm"] { padding: 0; border: 0; }
.st-key-config_row [data-testid="stHorizontalBlock"],
.st-key-config_provider_row [data-testid="stHorizontalBlock"] { display: grid; grid-template-columns: minmax(80px, 1fr) minmax(0, 3fr); align-items: center; gap: 1rem; }
.st-key-config_row [data-testid="stColumn"], .st-key-config_provider_row [data-testid="stColumn"] { min-width: 0; width: 100% !important; }
.st-key-result_summary { padding: .5rem 0; border-bottom: 1px solid var(--rule); }
.st-key-report_exports { margin-top: 1rem; padding-top: 1.25rem; border-top: 1px solid var(--rule); }
.st-key-course_panel [data-testid="stExpander"] { border: none; border-top: 1px solid var(--rule); border-radius: 0; }
.st-key-course_panel [data-testid="stExpander"] summary { padding-left: 0; }
.masthead-meta { text-align: right; color: var(--muted-ink); font-size: .8125rem; padding-top: .75rem; }
.mode-note { color: var(--forest); font-size: .8125rem; line-height: 1.7; margin: .25rem 0 1rem; }
.mode-note strong { font-weight: 600; }
.document-note { margin: .5rem 0; padding-top: .75rem; border-top: 1px solid var(--rule); }
.document-note strong { display: block; font-size: .9375rem; overflow-wrap: anywhere; }
.document-note span { color: var(--muted-ink); font-size: .8125rem; }
.reading-empty { padding: 3rem 1.5rem; max-width: 42rem; margin: 0 auto; }
.reading-empty h2 { margin: 0 0 1rem; font-size: 1.6rem; }
.reading-empty p { color: var(--muted-ink); margin: .5rem 0; }
.reading-empty .empty-line { margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--rule); font-size: .875rem; }
.workflow { list-style: none; padding: 0; margin: 1.5rem 0; }
.workflow li { padding: .625rem 0; display: flex; gap: .75rem; align-items: baseline; color: var(--muted-ink); }
.workflow .step-number { font-variant-numeric: tabular-nums; width: 1.25rem; font-size: .8125rem; }
.workflow .current { color: var(--forest); font-weight: 600; }
.workflow .done .step-number { color: var(--forest); }
.workflow small { display: block; font-size: .75rem; font-weight: 400; margin-top: .125rem; }
.review-state { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin: .5rem 0 1rem; font-size: .875rem; }
.review-state .state-label { color: var(--annotation); }
.review-state.confirmed .state-label { color: var(--forest); }
.evidence-quote { margin: .75rem 0 1rem; padding: 1rem 1.25rem; background: var(--inset); border-radius: 8px; }
.evidence-quote blockquote { color: var(--ink); opacity: 1; margin: 0; padding: 0; border: 0; font-family: var(--font-reading); font-size: .9375rem; line-height: 1.95; white-space: pre-wrap; overflow-wrap: anywhere; max-width: 72ch; }
.evidence-quote figcaption { margin-top: .75rem; padding-top: .5rem; border-top: 1px solid var(--rule); color: var(--annotation); font-size: .8125rem; }
.review-opinion-title { color: var(--forest); font-size: .875rem; font-weight: 600; margin-bottom: .5rem; }
.stApp ::selection { background: #D7E5D5; color: var(--ink); }
.stApp a { text-underline-offset: .2em; }
.stApp * { scrollbar-color: #A9B3A5 var(--paper); scrollbar-width: thin; }
@media (max-width: 1000px) {
  .stApp [data-testid="stMainBlockContainer"] { padding: 1.5rem 1.5rem 2rem; }
  .st-key-upload_panel, .st-key-course_panel { padding: 1rem; }
}
@media (max-width: 760px) {
  .stApp [data-testid="stMainBlockContainer"] { padding: 4.5rem 1rem 2rem; }
  .stApp h1 { font-size: 1.65rem; }
  .stApp [data-baseweb="tab-list"] { gap: 1.25rem; margin-bottom: 1rem; }
  .stApp [data-baseweb="tab"] p { font-size: .875rem; }
  .masthead-meta { text-align: left; padding-top: 0; }
  .masthead-meta { display: none; }
  .st-key-header_settings { top: 4.75rem; right: 1rem; }
  .stApp:has(.st-key-header_settings) h1 { padding-right: 48px; }
  .st-key-configuration_form { padding: 1rem; }
  .st-key-config_row [data-testid="stHorizontalBlock"], .st-key-config_provider_row [data-testid="stHorizontalBlock"] { grid-template-columns: 75px minmax(0, 1fr); gap: .5rem; }
  .reading-empty { padding: 1.5rem .5rem; }
  .evidence-quote { padding: .875rem; }
  .st-key-result_summary [data-testid="stHorizontalBlock"] { display: grid; grid-template-columns: minmax(0, 1.5fr) repeat(2, minmax(0, 1fr)); gap: .5rem; }
  .st-key-result_summary [data-testid="stColumn"] { min-width: 0 !important; width: 100% !important; }
  .stApp [data-testid="stMetricValue"] { font-size: 1.125rem; }
  .stApp [data-testid="stMetricLabel"] p { font-size: .75rem; }
}
@media (prefers-reduced-motion: reduce) {
  .stApp button { transition: none; }
}
</style>
"""


def apply_theme() -> None:
    st.markdown(STYLES, unsafe_allow_html=True)


def render_header(context: str) -> None:
    st.set_page_config(page_title=f"结课论文评价助手 · {context}", page_icon=":material/description:", layout="wide", initial_sidebar_state="auto")
    apply_theme()
    title_area, version_area = st.columns([5, 1.5])
    with title_area:
        st.title("结课论文评价助手")
        st.caption("AI辅助评价，最终成绩由教师确定")
    with version_area:
        st.markdown(f'<div class="masthead-meta" style="padding-right:56px">{escape(context)} · v{__version__}</div>', unsafe_allow_html=True)
    if context != "模型服务配置":
        from paper_assistant.routes import SETTINGS_PAGE
        with st.container(key="header_settings"):
            if st.button("模型服务配置", icon=":material/settings:", help="模型服务配置", key="open_header_settings"):
                st.switch_page(SETTINGS_PAGE)


def render_workflow(document, run, confirmed: bool) -> None:
    ready = document is not None and document.can_analyze
    active = 3 if run is not None else 2 if ready else 1 if document is not None else 0
    labels = (
        ("准备论文", "上传文件，选择课程标准"),
        ("核对文本", "确认页码与可提取内容"),
        ("参考评价", "查看分数、理由和原文"),
        ("教师复核", "记录依据，确认后导出"),
    )
    items = []
    for index, (label, note) in enumerate(labels):
        state = "done" if index < active or confirmed else "current" if index == active else ""
        items.append(f'<li class="{state}"><span class="step-number">{index + 1:02d}</span>'
                     f'<span>{label}</span></li>')
    st.markdown('<ol class="workflow" aria-label="评阅进度">' + "".join(items) + '</ol>', unsafe_allow_html=True)


def render_document_note(document) -> None:
    source = "内置演示文本" if document.source == "demo" else "已解析的论文"
    st.markdown(
        f'<div class="document-note"><strong>{escape(document.filename)}</strong>'
        f'<span>{source} · {len(document.pages)} 页 · {document.character_count:,} 字符 · {escape(document.parsing_status)}</span></div>',
        unsafe_allow_html=True,
    )


def render_empty_result() -> None:
    st.markdown(
        '<section class="reading-empty"><h2>暂无评价</h2>'
        '<p>上传论文后开始分析。</p></section>',
        unsafe_allow_html=True,
    )


def render_evidence(evidence: dict) -> None:
    st.markdown(
        '<figure class="evidence-quote">'
        f'<blockquote>{escape(evidence["quote"])}</blockquote>'
        f'<figcaption>已验证原文 · 物理第 {int(evidence["page"])} 页 · 片段 {escape(evidence["chunk_id"])}</figcaption>'
        '</figure>',
        unsafe_allow_html=True,
    )


def render_review_state(summary: dict) -> None:
    confirmed = bool(summary.get("confirmed"))
    st.markdown(
        f'<div class="review-state{" confirmed" if confirmed else ""}">'
        f'<span>复核后参考合计：<strong>{escape(summary["total_label"])}</strong></span>'
        f'<span class="state-label">{escape(summary["status"])}</span></div>',
        unsafe_allow_html=True,
    )

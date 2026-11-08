"""固定模式的原生页面路由；页面模式不接受URL参数或界面开关覆盖。"""

import streamlit as st


PRODUCTION_PAGE = "paper_assistant/pages/production.py"
ENTRANCE_PAGE = "paper_assistant/pages/entrance.py"
DEMO_PAGE = "paper_assistant/pages/demo.py"
SETTINGS_PAGE = "paper_assistant/pages/settings.py"


def run_app() -> None:
    st.navigation([
        st.Page(ENTRANCE_PAGE, title="结课论文评价助手", default=True),
        st.Page(PRODUCTION_PAGE, title="正式评阅", icon=":material/article:", url_path="review"),
        st.Page(DEMO_PAGE, title="模拟运行", icon=":material/science:", url_path="demo"),
        st.Page(SETTINGS_PAGE, title="模型服务配置", icon=":material/settings:", url_path="settings"),
    ], position="hidden").run()


def render_entry_links(*, demo: bool = False) -> None:
    st.page_link(PRODUCTION_PAGE, label="正式评阅", icon=":material/article:")
    if demo:
        st.page_link(DEMO_PAGE, label="模拟运行", icon=":material/science:")


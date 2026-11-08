"""可立即跳过的摄影入口；原生按钮保留键盘和读屏操作。"""

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

from paper_assistant.routes import PRODUCTION_PAGE


@lru_cache(maxsize=2)
def _photo(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / "entrance" / name
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def main() -> None:
    st.set_page_config(page_title="结课论文评价助手", page_icon=":material/auto_stories:", layout="wide", initial_sidebar_state="collapsed")
    paused = st.session_state.get("entrance_paused", False)
    library, pages = _photo("library.jpg"), _photo("pages.jpg")
    css = (Path(__file__).resolve().parents[1] / "assets/entrance/entrance.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    st.markdown(
        '<main class="entrance' + (' entrance-paused' if paused else '') + '">'
        '<div class="entrance-photos" aria-hidden="true">'
        '<div class="entrance-camera"><div class="entrance-parallax">'
        f'<div class="photo-library" style="background-image:url({library})"></div>'
        f'<div class="photo-pages" style="background-image:url({pages})"></div>'
        '<div class="folio-stack">'
        + ''.join(f'<div class="folio-sheet folio-sheet-{i}" style="background-image:url({pages});--sheet:{i}"></div>' for i in range(3))
        + '</div></div></div>'
        '<div class="photo-shade"></div></div>'
        '<div class="entrance-top"><span>结课论文评价助手</span></div>'
        '<div class="entrance-copy"><h1>让每一篇论文，<br>被认真读过。</h1>'
        '</div>'
        '<div class="entrance-bottom"><div class="entrance-invitation">点击进入'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 12h15M13 5l7 7-7 7"/></svg>'
        '</div>'
        '<p>AI辅助评价，最终成绩由教师确定</p></div>'
        '<div class="entrance-credit">摄影 Janko Ferlič / Patrick Tomasso · Unsplash</div>'
        '</main>', unsafe_allow_html=True,
    )
    if st.button("进入评阅工作台", key="enter_workspace", width="stretch"):
        st.switch_page(PRODUCTION_PAGE)
    with st.container(key="entrance_motion"):
        st.toggle("暂停动态效果", key="entrance_paused")
    script = (Path(__file__).resolve().parents[1] / "assets/entrance/entrance.js").read_text(encoding="utf-8")
    st.html(f"<script>/* paused={int(paused)} */\n{script}</script>", unsafe_allow_javascript=True)

"""Streamlit 启动入口。业务逻辑位于 paper_assistant 包。"""

from paper_assistant.routes import run_app


if __name__ == "__main__":
    run_app()

@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PAPER_ASSISTANT_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PAPER_ASSISTANT_PYTHON=%~dp0.venv\Scripts\python.exe"

"%PAPER_ASSISTANT_PYTHON%" -c "import streamlit, pypdf, pdfplumber, dotenv, httpx" >nul 2>&1
if errorlevel 1 (
    echo 尚未找到 Python 或所需依赖，请按照 README.md 安装依赖后重试。
    echo 安装命令：python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo 正在启动“结课论文评价助手”……
echo 动态展示：http://127.0.0.1:8501/
echo 正式评阅：http://127.0.0.1:8501/review
echo 模拟运行：http://127.0.0.1:8501/demo
echo 模型配置：http://127.0.0.1:8501/settings
echo 请保持本窗口运行；关闭窗口或按 Ctrl+C 会停止网页服务。
echo 如果提示端口被占用，请先打开上述地址查看已有应用。
echo.
"%PAPER_ASSISTANT_PYTHON%" -m streamlit run app.py --server.headless false
if errorlevel 1 (
    echo.
    echo 应用未能启动，请保留上方错误信息并联系项目维护同事。
    pause
    exit /b 1
)

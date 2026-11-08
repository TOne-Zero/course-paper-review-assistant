@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PAPER_WEB_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PAPER_WEB_PYTHON%" set "PAPER_WEB_PYTHON=python"
"%PAPER_WEB_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/state',timeout=2)" >nul 2>&1
if not errorlevel 1 (
  echo 应用已经运行：http://127.0.0.1:8765/
  echo 正式评阅：http://127.0.0.1:8765/?view=workspace
  echo 模拟运行：http://127.0.0.1:8765/?mode=demo^&view=workspace
  pause
  exit /b 0
)
"%PAPER_WEB_PYTHON%" -c "import pdfplumber,pypdf,dotenv,httpx" >nul 2>&1
if errorlevel 1 (
  echo 缺少Python依赖，请先使用虚拟环境安装requirements.txt。
  pause
  exit /b 1
)
if not exist "frontend\dist-app\index.html" (
  pushd frontend
  call npm.cmd ci
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  call npm.cmd run build
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
)
echo 正在启动完整应用：http://127.0.0.1:8765/
echo 正式评阅：http://127.0.0.1:8765/?view=workspace
echo 模拟运行：http://127.0.0.1:8765/?mode=demo^&view=workspace
echo 请保持本窗口运行；按Ctrl+C停止。
"%PAPER_WEB_PYTHON%" -m paper_assistant.web_service --port 8765
if errorlevel 1 pause

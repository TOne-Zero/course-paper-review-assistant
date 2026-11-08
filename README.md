# 结课论文评价助手

面向教师的本地论文批量评阅工具。上传 Word 或 PDF，选择评分标准，使用自己的模型 API 生成有原文引用的参考评价，再由教师复核并导出报告。

**AI 辅助评价，最终成绩由教师确定。** 本项目不判定抄袭或研究真实性，也不自动提交成绩。

## 功能

- 支持 `.pdf`、`.docx`、`.doc` 混合上传，每批最多 **10 篇**，单篇 **20 MB**，合计 **50 MB**，默认每篇最多 100 页。
- 三套内置标准：课程论文综合评价、通识课程论文、研究方法课程论文。可编辑维度权重、逐条细则和每条分值，总分 100 分。
- 批量进度、生成中的理由草稿、分数分布、维度图表；失败保留错误，不以模拟分数补齐。
- 逐页原文、经程序核对存在的摘录、扣分理由、修改建议，以及独立的教师修改记录。
- 导出 ZIP，内含每篇 Markdown、JSON 和批次清单；目前不直接生成 Word/PDF 格式报告。
- 独立模拟入口，使用原创虚构示例和固定比例分数，不请求外部模型。

前端采用 React 18 / TypeScript / Tailwind CSS / ECharts 5；Python 后端同时提供 API 和构建后的前端。

## 环境要求

| 软件 | 用途 |
| --- | --- |
| Python 3.11 或 3.12 | 后端；已在 Python 3.12 下验证 |
| Node.js 20 或 22，含 npm | 构建前端；使用仓库内 package-lock.json |
| Git | 克隆仓库，也可下载源码 ZIP |
| LibreOffice，或 Windows 上的 Microsoft Word | 仅上传 Word 时需要；只使用 PDF 可不安装 |
| 可用的模型 API | 仅正式评阅需要；模拟运行无需密钥 |

## 本地部署

```bash
git clone https://github.com/TOne-Zero/course-paper-review-assistant.git
cd course-paper-review-assistant
```

以下命令从仓库根目录执行。不要复制其他电脑的虚拟环境或 node_modules。

### Windows：PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env

cd frontend
npm ci
npm run build
cd ..

.\.venv\Scripts\python.exe -m paper_assistant.web_service --port 8765
```

没有 `py` 时，使用指向 Python 3.11/3.12 的 `python` 创建虚拟环境。不必激活环境，也不必修改 PowerShell 执行策略。已有 `.env` 时保留原文件，不要覆盖。

首次安装后，也可双击 **启动应用.cmd** 或 **启动完整应用.cmd**。脚本优先使用 `.venv`，前端构建缺失时会执行 npm 安装和构建；不会自动创建 Python 环境或安装 Python 依赖。

### macOS / Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env

cd frontend
npm ci
npm run build
cd ..

.venv/bin/python -m paper_assistant.web_service --port 8765
```

也可使用已安装的 `python3.11`。本轮实际部署验证环境为 Windows；提供其他平台操作步骤，不代表所有操作系统均已实测。

保持服务终端运行，按 Ctrl+C 停止。**启动 Python 即同时提供前端和 API，不需要另开 Vite。**

| 页面 | 地址 |
| --- | --- |
| 开屏 | <http://127.0.0.1:8765/> |
| 正式评阅 | <http://127.0.0.1:8765/?view=workspace> |
| 模拟运行 | <http://127.0.0.1:8765/?mode=demo&view=workspace> |
| 评分标准设置 | <http://127.0.0.1:8765/?view=workspace&settings=criteria> |

## 首次使用

1. 打开**模拟运行**，点击“载入示例论文”，开始评阅，体验复核和导出。示例及分数均为虚构演示，不是真实成绩。
2. 打开**正式评阅**，点右上角齿轮进入 AI 模型配置。选择服务商或自定义，填 API 地址、模型标识和密钥，测试成功后保存。
3. 上传论文并选择标准。可在设置中心修改细则及分值；保存评分条件会清除相关旧评分和复核，需要确认。
4. 点击“开始评阅”，确认把本批提取文字发送给已配置服务。处理中点击论文可查看实际阶段和理由草稿；草稿尚未校验，以最终报告为准。
5. 在结果复核中核对分项和原文，记录教师修改，导出报告。

正式与模拟入口使用独立会话。学生身份需核对原文，系统不会把文件名推断当成已确认身份。

### 模型配置

也可编辑根目录 `.env`，修改后重启服务：

```dotenv
MODEL_BASE_URL=https://api.example.com/v1
MODEL_NAME=你的模型标识
MODEL_API_KEY=你的密钥
```

上方地址仅为示意，需替换成服务商文档规定的实际地址；模型标识和密钥必须匹配。系统环境变量优先于 `.env`。

已适配常见 Chat Completions、Responses、Anthropic Messages、Gemini 协议。无效地址、认证失败、网络限制或不兼容模型仍会如实报错，不承诺任意 API 都能成功。

网页首次打开时地址、模型和密钥输入为空，不回填后台凭据，**不表示后台配置丢失**。本页输入并保存后，关闭重开会保留，密钥可用眼睛切换显示；刷新后释放前端输入，后台已保存配置仍可使用。同地址留空可沿用后台密钥，换地址需重新填写。

默认 `MODEL_MAX_OUTPUT_TOKENS=0`，支持省略的协议不主动指定输出长度上限；服务商仍有限制，原生 Anthropic 协议还要求必填输出上限。超时、调用次数和输入容量限制保留，详见 [模型接口说明](docs/API兼容与JSON恢复说明.md)。

## Word 和 PDF 读取

PDF 在本机提取文字，**没有 OCR**；扫描件需要先转换为带可搜索文字的 PDF。复杂表格、公式、图像和阅读顺序仍需人工核对，无法可靠提取的页不会冒充已评阅。

Word 先在本机转换成 PDF，再复用分页解析与引用校验：

- 优先查找 LibreOffice 的 `soffice`；Windows 还会检查常见安装目录。未找到时，Windows 尝试调用已安装、可正常打开文件的 Microsoft Word。
- macOS / Linux 请安装 [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/)，使 `soffice` 位于 PATH。macOS 应用版可在启动前执行 `export PATH="/Applications/LibreOffice.app/Contents/MacOS:$PATH"`。
- Word 引用页码对应**本次转换版本**，可能因字体和排版与原 Word 显示不同；保留原文件名、来源及 SHA-256。
- 临时文件位于 `.runtime/word-conversion/` 的隔离子目录，完成或失败后清理，不覆盖原件；单次转换最长 90 秒。Windows Word 自动化禁用宏和打开时链接更新。

Office / LibreOffice 由部署者另行安装，仓库不包含它们。

## 数据与运行边界

- 默认仅监听 `127.0.0.1`，面向本机使用；没有登录、多人权限或持久化成绩数据库，请勿直接暴露到公网。
- 论文、解析文本、评分和复核保存在后端内存会话中；刷新页面通常保留，服务重启或会话过期会丢失，请及时下载报告。
- 模型配置保存于本机 `.env`；自定义评分标准保存在 `rubrics/user_settings/`，正式与模拟分别保存。
- 正式评阅会向选定服务发送提取文字、页码及评分要求，可能产生费用；请确保论文有相应授权，并核对服务商的数据政策。
- 仓库不含真实论文、个人密钥、分析报告、开发者环境或历史截图，仅提供空白配置示例和原创虚构论文。
- 原文摘录通过存在校验，不代表 AI 推理、文献真实性或评分准确性已经获得证明。

## 开发与测试

后端按部署步骤启动。另开终端运行前端开发服务器：

```bash
cd frontend
npm ci
npm run dev
```

访问 <http://127.0.0.1:5173/>，Vite 将 `/api` 转发到 8765。正式本地使用仍执行 `npm run build`，由 Python 提供 `frontend/dist-app/`。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

macOS / Linux 将解释器替换为 `.venv/bin/python`。自动测试使用原创虚构文件、临时配置和受控模型响应，不需要真实 API 密钥，不代表评分效度验证。


## 常见问题

| 问题 | 处理 |
| --- | --- |
| 网页打不开 | 保持 Python 服务终端运行，检查端口；打开网址本身不会启动服务 |
| 8765 被占用 | 改用 `--port 8766` 并访问 8766；开发代理需同步改端口 |
| 缺少前端构建 | 在 frontend 运行 `npm ci`、`npm run build` |
| 依赖安装失败 | 检查 Python 版本、网络和包索引，保留完整报错排查 |
| 测试连接成功但评阅失败 | 小请求测试不验证长文、费用、上下文及结构化评分能力，查看该篇错误提示 |
| Word 读取失败 | 检查转换器和文件是否加密、损坏，也可先自行另存 PDF |
| 分数为空 | 表示无法判断或校验失败，不当作零分；核对原文和教师复核 |

## 目录与许可

```text
paper_assistant/     Python 解析、模型适配、校验、评分和报告
frontend/    React 源码、依赖锁文件及字体许可
rubrics/            三套内置评分标准
examples/           原创虚构 PDF 和文本源
tests/              自动测试及虚构文件生成器
references/         标准设计参考依据
docs/               运行及接口补充说明
```

当前未附加项目代码许可证。第三方组件、字体及摄影的出处和许可见 [OPEN_SOURCE.md](OPEN_SOURCE.md) 及各自许可文件；它们不替代项目本身的许可证。

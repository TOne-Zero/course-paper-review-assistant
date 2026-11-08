# 开源组件、出处与采用范围

2026-11-01 新增展示页摄影：Janko Ferlič 的图书馆照片及 Patrick Tomasso 的书页照片，均按 Unsplash License 下载并本地保存。作者、原照片链接、许可和下载源见 [摄影来源记录](assets/entrance/SOURCES.md)，来源同时嵌入 JPEG 元数据。图片仅为入口视觉，不是被评阅的论文或本项目功能证明。

核对日期：2026-10-30。项目使用现有开源库，不声称原创 PDF 识别算法。

| 组件 | 本项目采用内容 | 出处与许可 |
| --- | --- | --- |
| pdfplumber 0.11.10 | 默认文字提取器，去重、按字符位置组行；格式模块另调用 `find_tables()` 作保守的表格风险排除，不认证复杂版式；不上传文件、不下载模型 | [官方仓库和接口文档](https://github.com/jsvine/pdfplumber)、[MIT 许可证](https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt)，Copyright (c) 2015 Jeremy Singer-Vine |
| pdfminer.six | pdfplumber 的底层 PDF 字符与版面分析依赖 | [官方仓库](https://github.com/pdfminer/pdfminer.six)、[字符/行/文本框组装原理](https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html)、[MIT 许可证](https://github.com/pdfminer/pdfminer.six/blob/master/LICENSE)，Copyright (c) 2004-2016 Yusuke Shinyama |
| pypdf 6.21.2 | 校验页数、加密状态、图像标记；读取 MediaBox / UserUnit / rotation 作为信息；可选择的文字提取对照和异常回退 | [官方仓库](https://github.com/py-pdf/pypdf)、[BSD-3-Clause 许可证](https://github.com/py-pdf/pypdf/blob/main/LICENSE) |

使用的是库公开接口，没有复制第三方整段算法源码。第三方组件的版权和许可保留在各依赖发行包中，打包或分发依赖时应一并保留其许可证。本文件是组件出处记录，不替代第三方许可证。

## 0.5.0 模型接口与演示素材出处

- [HTTPX官方文档](https://www.python-httpx.org/)：使用0.28.1发送兼容Chat Completions请求；测试用其 `MockTransport` 构造受控成功/失败响应，未将测试响应冒充真实服务评价。不是复制第三方评分算法。
- [OpenAI结构化输出说明](https://developers.openai.com/api/docs/guides/structured-outputs) 与 [Chat Completions接口说明](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)：作为消息、JSON格式参数和响应结构的协议参考。JSON模式不能替代本地分值、必填字段及原文来源校验。
- [ReportLab开源工具包](https://docs.reportlab.com/)：仅用于将本项目原创虚构文本生成3页演示PDF，依赖单独列在 `requirements-demo.txt`；应用运行不依赖它。
- `examples/demo_paper.json` 是本项目原创演示内容，没有挪用学生论文；文中的教学记录和参考资料明确标为虚构或占位，不宣称它们是真实研究或可引用来源。

逐页完整分段、维度提示词、证据校验、教师复核和报告逻辑由本项目实现；不声称拥有模型厂商能力，也不承诺评分准确性。正式评阅使用部署者配置的模型服务；自动测试中的受控响应不证明评分效度。

## 本项目额外完成的适配

- `pdf_text_backend.py` 封装两个提取器，异常回退会明确记录；`.env` 中可设置 `PDF_TEXT_ENGINE=pdfplumber` 或 `pypdf`。
- `section_locator.py` 是项目的章节边界规则，不是 pdfplumber 自带的“正文识别模型”：支持编号首节（例如问题重述、研究背景）、拆行编号、关键词之后的低把握回退；正文延伸到参考文献、附录、致谢或声明之前，而非只截取第一节。
- `document_exporter.py` 按候选范围组装完整正文和逐页 JSON，保留物理页码并去除明显的页尾数字页码；页面不可判断时保留缺口。
- `ui.py` 展示识别依据、完整正文候选和下载入口；不把规则结果宣称为一定准确。
- `format_checker.py` 是本项目基于明确证据的三态检查逻辑，未宣称来自任何学校或开源库的官方格式认证；表格检测仅用于避免把解析不确定性误判为违规。演示规范均为项目自拟。

## 已检索但本轮未接入的方案

- [PyMuPDF4LLM](https://github.com/pymupdf/pymupdf4llm)：面向 Markdown 和阅读顺序的方案；[官方许可为 AGPL-3.0](https://github.com/pymupdf/pymupdf4llm/blob/main/LICENSE)。本轮没有引入其代码或依赖。
- [Docling](https://github.com/docling-project/docling)：提供版面、阅读顺序、表格和 OCR 管道，可作为复杂版面后续方案；本轮没有安装或下载模型，也没有宣称完成该引擎的效果验证。


## 前端与本地转换

React、Vite、Tailwind CSS、Radix UI、ECharts、fflate、Inter及Noto Serif SC通过npm安装。依赖包许可保留在各发行包中，自托管字体许可随仓库提供于frontend-preview/public/licenses/。Word转换使用部署者自行安装的LibreOffice或Windows Microsoft Word，不随仓库分发。项目代码当前未附加许可证，本文件只记录第三方出处。

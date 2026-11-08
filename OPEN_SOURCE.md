# 第三方组件与许可

项目使用以下组件的公开接口，不声称原创 PDF 提取算法或拥有模型厂商能力。

| 组件 | 用途与来源 |
| --- | --- |
| pdfplumber | 默认PDF文字与字符位置读取；[源码与MIT许可](https://github.com/jsvine/pdfplumber) |
| pdfminer.six | pdfplumber依赖的PDF字符/版面分析；[源码与MIT许可](https://github.com/pdfminer/pdfminer.six) |
| pypdf | 页数、加密状态、页面信息及可选文字提取；[源码与BSD许可](https://github.com/py-pdf/pypdf) |
| HTTPX、python-dotenv | HTTP请求与本机环境配置；许可随其Python发行包提供 |
| React、Vite、Tailwind CSS、Radix UI、ECharts、fflate | 前端运行、构建、图表与下载；版本由frontend/package-lock.json固定，许可随npm发行包提供 |
| Inter、Noto Serif SC | 自托管字体；随仓库提供的OFL许可见frontend/public/licenses/ |

Word转换调用部署者另行安装的LibreOffice或Windows Microsoft Word，不随仓库分发。最终React封面通过代码实现，不使用摄影素材。

examples/中的演示PDF为原创虚构内容，不含真实学生资料，不代表真实研究。标准设计依据见references/，并非学校官方标准或经过评分效度验证的量表。

当前未附加项目代码许可证。本文件记录第三方出处，不替代第三方或项目自身的许可。

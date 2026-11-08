# React 与 Python 本地运行

完整安装命令、环境要求、Word转换和模型设置见[根目录README](../README.md)。新版默认8765端口，Python同时提供dist-app和API；开发模式另开5173，由Vite代理API。不要只运行前端后期待API自动启动。前端升级后重新npm run build，后端代码升级需重启，内存中的未导出结果会清空。模型配置.env和评分配置rubrics/user_settings可单独备份，但不要提交仓库。

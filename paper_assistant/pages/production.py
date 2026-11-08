"""正式入口始终使用真实模型，配置缺失时禁止分析。"""

from paper_assistant.ui import main

main(mode="real")

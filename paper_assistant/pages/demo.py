"""模拟入口始终使用本地演示逻辑，不调用外部模型。"""

from paper_assistant.ui import main

main(mode="mock")

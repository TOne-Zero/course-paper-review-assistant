"""已核对官方文档的文本模型地址预设，不推测可用模型。"""

from dataclasses import dataclass

from paper_assistant.schemas import AssistantError


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    documentation: str
    note: str = "模型名称请从该服务账号的可用模型列表中复制。"


PROVIDERS = (
    Provider("自定义", "", "", "填写 API 根地址或完整接口地址；支持 Chat Completions、Responses、Anthropic Messages 与 Gemini 原生接口。"),
    Provider("OpenAI", "https://api.openai.com/v1", "https://developers.openai.com/api/reference/resources/chat"),
    Provider("Anthropic", "https://api.anthropic.com/v1", "https://platform.claude.com/docs/en/api/messages/create", "使用原生Messages接口；输出上限为该协议必填，优先读取模型公布的上限。"),
    Provider("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "https://ai.google.dev/gemini-api/docs/openai/"),
    Provider("DeepSeek", "https://api.deepseek.com", "https://api-docs.deepseek.com/quick_start/agent_integrations/"),
    Provider("Qwen · 阿里云百炼（北京）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "https://help.aliyun.cn/zh/model-studio/model-calling-in-sub-workspace", "此预设为北京地域通用 API。其它地域、业务空间或套餐请按控制台修改地址，密钥需与地址配套。"),
    Provider("GLM · 智谱", "https://open.bigmodel.cn/api/paas/v4", "https://docs.bigmodel.cn/cn/guide/develop/openai/introduction", "通用 API 地址；Coding Plan 等套餐请按服务商文档确认用途和专用地址。"),
    Provider("Kimi · Moonshot", "https://api.moonshot.cn/v1", "https://platform.kimi.com/docs/api/overview"),
    Provider("SiliconFlow · 硅基流动", "https://api.siliconflow.cn/v1", "https://api-docs.siliconflow.cn/docs/userguide/quickstart"),
    Provider("Ollama（本地）", "http://localhost:11434/v1", "https://docs.ollama.com/api/openai-compatibility", "先在本机启动 Ollama 并准备模型。本地 Ollama 忽略密钥，预填的 ollama 仅为兼容占位值。"),
)
BY_NAME = {provider.name: provider for provider in PROVIDERS}


def provider_for_url(url: str) -> str:
    normalized = url.strip().rstrip("/")
    return next((item.name for item in PROVIDERS if item.base_url and item.base_url == normalized), "自定义")


def resolve_api_key(base_url: str, entered: str, previous: dict[str, str]) -> str:
    """地址变化后禁止静默把原密钥用于新服务；新密钥必须显式填写。"""
    if entered.strip():
        return entered.strip()
    if base_url.strip().rstrip("/") != previous.get("MODEL_BASE_URL", "").strip().rstrip("/"):
        if previous.get("MODEL_API_KEY"):
            raise AssistantError("服务地址已更改，请重新填写该服务的 API 密钥。原密钥不会用于新地址。")
        return ""
    return previous.get("MODEL_API_KEY", "").strip()

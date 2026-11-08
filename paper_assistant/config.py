"""集中读取运行配置；.env 仅从项目根目录读取。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from paper_assistant.schemas import AssistantError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    mode: str = "mock"
    max_pdf_mb: int = 20
    max_pdf_pages: int = 100
    max_text_characters: int = 200_000
    min_page_text_characters: int = 30
    min_document_text_characters: int = 50
    pdf_text_engine: str = "pdfplumber"
    model_api_key: str = field(default="", repr=False, compare=False)
    model_name: str = ""
    model_base_url: str = ""
    model_timeout_seconds: int = 45
    model_chunk_characters: int = 3000
    model_batch_characters: int = 12000
    model_max_prompt_characters: int = 40000
    model_max_synthesis_characters: int = 24000
    model_max_calls: int = 40
    model_max_output_tokens: int = 0  # 0: 请求中不发送输出token上限。
    model_response_format: str = "json_object"
    model_token_parameter: str = "max_tokens"


def configuration_values() -> dict[str, str]:
    """每次重新读取本机配置；不把 .env 注入进程，保留系统变量优先级。"""
    try:
        local = dotenv_values(LOCAL_ENV_PATH, encoding="utf-8-sig", interpolate=False)
    except (OSError, UnicodeError):
        raise AssistantError("无法读取本机 .env，请检查文件权限和 UTF-8 编码。") from None
    return {**{key: value for key, value in local.items() if value is not None}, **os.environ}


def load_settings(*, mode: str | None = None) -> Settings:
    values = configuration_values()
    selected_mode = mode if mode is not None else values.get("ANALYSIS_MODE", "mock").strip().lower()

    def positive_int(name: str, default: int, *, allow_zero=False) -> int:
        try:
            value = int(values.get(name, str(default)))
        except ValueError:
            raise AssistantError(f"配置 {name} 必须是正整数，请检查 .env。") from None
        if value < 0 or (value == 0 and not allow_zero):
            raise AssistantError(f"配置 {name} 必须大于 0，请检查 .env。")
        return value

    if selected_mode not in {"mock", "real"}:
        raise AssistantError("ANALYSIS_MODE 仅支持 mock 或 real。")
    engine = values.get("PDF_TEXT_ENGINE", "pdfplumber").strip().lower()
    if engine not in {"pdfplumber", "pypdf"}:
        raise AssistantError("PDF_TEXT_ENGINE 仅支持 pdfplumber 或 pypdf。")
    document_settings = dict(
        mode=selected_mode,
        max_pdf_mb=positive_int("MAX_PDF_MB", 20),
        max_pdf_pages=positive_int("MAX_PDF_PAGES", 100),
        max_text_characters=positive_int("MAX_TEXT_CHARACTERS", 200_000),
        min_page_text_characters=positive_int("MIN_PAGE_TEXT_CHARACTERS", 30),
        min_document_text_characters=positive_int("MIN_DOCUMENT_TEXT_CHARACTERS", 50),
        pdf_text_engine=engine,
    )
    # 固定的模拟入口不依赖真实服务配置，损坏的模型参数也不应阻断模拟流程。
    if mode == "mock":
        return Settings(**document_settings)
    return Settings(
        **document_settings,
        model_api_key=values.get("MODEL_API_KEY", "").strip(),
        model_name=values.get("MODEL_NAME", "").strip(),
        model_base_url=values.get("MODEL_BASE_URL", "").strip(),
        model_timeout_seconds=positive_int("MODEL_TIMEOUT_SECONDS", 45),
        model_chunk_characters=positive_int("MODEL_CHUNK_CHARACTERS", 3000),
        model_batch_characters=positive_int("MODEL_BATCH_CHARACTERS", 12000),
        model_max_prompt_characters=positive_int("MODEL_MAX_PROMPT_CHARACTERS", 40000),
        model_max_synthesis_characters=positive_int("MODEL_MAX_SYNTHESIS_CHARACTERS", 24000),
        model_max_calls=positive_int("MODEL_MAX_CALLS", 40),
        model_max_output_tokens=positive_int("MODEL_MAX_OUTPUT_TOKENS", 0, allow_zero=True),
        model_response_format=values.get("MODEL_RESPONSE_FORMAT", "json_object").strip(),
        model_token_parameter=values.get("MODEL_TOKEN_PARAMETER", "max_tokens").strip(),
    )

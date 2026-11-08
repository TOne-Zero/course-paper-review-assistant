"""模型配置的本地原子保存；不联网、不更改系统环境变量。"""

import os
from pathlib import Path
import tempfile

from dotenv import set_key

from paper_assistant import config
from paper_assistant.api_transport import validate_api_settings
from paper_assistant.config import Settings
from paper_assistant.schemas import AssistantError


MODEL_FIELDS = {
    "MODEL_BASE_URL": "model_base_url",
    "MODEL_NAME": "model_name",
    "MODEL_API_KEY": "model_api_key",
    "MODEL_TIMEOUT_SECONDS": "model_timeout_seconds",
    "MODEL_MAX_OUTPUT_TOKENS": "model_max_output_tokens",
    "MODEL_MAX_CALLS": "model_max_calls",
    "MODEL_CHUNK_CHARACTERS": "model_chunk_characters",
    "MODEL_BATCH_CHARACTERS": "model_batch_characters",
    "MODEL_MAX_PROMPT_CHARACTERS": "model_max_prompt_characters",
    "MODEL_MAX_SYNTHESIS_CHARACTERS": "model_max_synthesis_characters",
    "MODEL_RESPONSE_FORMAT": "model_response_format",
    "MODEL_TOKEN_PARAMETER": "model_token_parameter",
}


def save_model_settings(settings: Settings, *, env_path: Path | None = None) -> None:
    """先校验所有字段，再一次替换 .env；不回显密钥或底层异常。"""
    validate_api_settings(settings)
    updates = {name: str(getattr(settings, field)) for name, field in MODEL_FIELDS.items()}
    controlled = [name for name, value in updates.items()
                  if name in os.environ and os.environ[name].strip() != value]
    if controlled:
        raise AssistantError("以下配置由系统环境变量控制，网页保存无法覆盖：" + "、".join(controlled)
                             + "。请先在启动应用的终端或系统设置中修改/取消这些变量，再重新启动应用。")
    path = Path(env_path) if env_path is not None else config.LOCAL_ENV_PATH
    if path.is_symlink():
        raise AssistantError("本地 .env 是链接文件，未写入。请使用项目目录内的普通配置文件。")
    temporary = None
    try:
        original = path.read_text(encoding="utf-8-sig") if path.exists() else "# 本机模型服务配置；请勿分享或提交此文件。\n"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".env.", suffix=".tmp",
                                         dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(original)
        for name, value in updates.items():
            set_key(str(temporary), name, value, quote_mode="always", encoding="utf-8")
        os.replace(temporary, path)
        temporary = None
    except (OSError, UnicodeError):
        raise AssistantError("配置保存失败：请检查项目目录写入权限及 .env 是否为 UTF-8 文本。原配置未被替换。") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

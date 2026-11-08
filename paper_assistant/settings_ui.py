"""服务商连接卡片与本地保存；不自动发起外部请求。"""

from dataclasses import replace
import os

import streamlit as st

from paper_assistant.api_transport import validate_api_settings
from paper_assistant.config import Settings, configuration_values, load_settings
from paper_assistant.model_configuration import MODEL_FIELDS, save_model_settings
from paper_assistant.presentation import render_header
from paper_assistant.privacy import configure_private_logging
from paper_assistant.providers import BY_NAME, provider_for_url, resolve_api_key
from paper_assistant.routes import PRODUCTION_PAGE
from paper_assistant.schemas import AssistantError


def _integer(values, name, default, lower, upper=None):
    try:
        value = int(values.get(name, default))
    except (ValueError, TypeError):
        return default
    return value if value >= lower and (upper is None or value <= upper) else default


def _provider_changed():
    provider = BY_NAME[st.session_state["config_provider"]]
    st.session_state["config_base_url"] = provider.base_url
    st.session_state["config_api_key"] = "ollama" if provider.name == "Ollama（本地）" else ""
    st.session_state["config_model_name"] = ""


def _row(label):
    name, field = st.columns([1, 3], gap="small", vertical_alignment="center")
    name.markdown(label)
    return field


def _request_options(values):
    """后台预设；保留有效的部署环境值，损坏字段恢复安全默认值。"""
    formats = {"json_object", "json_schema", "none"}
    parameters = {"max_tokens", "max_completion_tokens"}
    response_format = values.get("MODEL_RESPONSE_FORMAT", "json_object")
    token_parameter = values.get("MODEL_TOKEN_PARAMETER", "max_tokens")
    options = {"model_response_format": response_format if response_format in formats else "json_object",
               "model_token_parameter": token_parameter if token_parameter in parameters else "max_tokens"}
    definitions = (
            ("model_timeout_seconds", "单次请求超时（秒）", "MODEL_TIMEOUT_SECONDS", 45, 1, 120, "config_timeout"),
            ("model_max_output_tokens", "单次最大输出 token 数（0不传上限）", "MODEL_MAX_OUTPUT_TOKENS", 0, 0, None, "config_output_tokens"),
            ("model_max_calls", "每轮最大请求次数", "MODEL_MAX_CALLS", 40, 1, 100, "config_max_calls"),
            ("model_chunk_characters", "单个原文片段字数", "MODEL_CHUNK_CHARACTERS", 3000, 1, 32000, "config_chunk_characters"),
            ("model_batch_characters", "每批原文字数", "MODEL_BATCH_CHARACTERS", 12000, 1, 32000, "config_batch_characters"),
            ("model_max_prompt_characters", "序列化提示字数上限", "MODEL_MAX_PROMPT_CHARACTERS", 40000, 1, None, "config_prompt_characters"),
            ("model_max_synthesis_characters", "单维度合成字数上限", "MODEL_MAX_SYNTHESIS_CHARACTERS", 24000, 1, None, "config_synthesis_characters"),
    )
    for field, _label, env, default, lower, upper, _key in definitions:
        options[field] = _integer(values, env, default, lower, upper)
    if options["model_chunk_characters"] > options["model_batch_characters"]:
        options.update(model_chunk_characters=3000, model_batch_characters=12000)
    return options


def main() -> None:
    configure_private_logging()
    render_header("模型服务配置")
    st.page_link(PRODUCTION_PAGE, label="返回评阅", icon=":material/arrow_back:")
    if st.session_state.pop("configuration_success", False):
        st.session_state.pop("config_api_key", None)
        st.success("已保存。格式校验通过，尚未验证服务连通性。")
    try:
        values = configuration_values()
    except AssistantError as error:
        st.error(str(error))
        return
    try:
        current = load_settings(mode="real")
        validate_api_settings(current)
        ready = True
    except AssistantError:
        current = Settings(mode="real")
        ready = False

    st.session_state.setdefault("config_provider", provider_for_url(values.get("MODEL_BASE_URL", "")))
    st.session_state.setdefault("config_base_url", values.get("MODEL_BASE_URL", ""))
    st.session_state.setdefault("config_model_name", values.get("MODEL_NAME", ""))
    form_area, guide_area = st.columns([1.3, 1], gap="large")
    with form_area, st.container(key="configuration_form"):
        with st.container(key="provider_heading"):
            st.subheader("模型服务")
            st.caption("已保存" if ready else "未配置")
        with st.container(key="config_provider_row"):
            with _row("服务商"):
                provider_name = st.selectbox("服务商", list(BY_NAME), key="config_provider", label_visibility="collapsed", on_change=_provider_changed)
        provider = BY_NAME[provider_name]
        with st.form("model_service_configuration", border=False):
            with st.container(key="config_row"):
                with _row("API URL"):
                    base_url = st.text_input("API 服务地址 *", key="config_base_url", label_visibility="collapsed",
                        placeholder="https://api.example.com/v1", help="预设会自动填入地址，也可以按控制台修改完整的 API 根地址。")
                with _row("API 密钥"):
                    api_key = st.text_input("API 密钥 *", type="password", key="config_api_key", autocomplete="off",
                        label_visibility="collapsed", placeholder="同一服务留空保留原密钥" if values.get("MODEL_API_KEY") else "仅填写密钥本身",
                        help="无需添加 Bearer。更换服务地址时必须重新填写密钥，不会沿用旧服务的密钥。")
            if values.get("MODEL_API_KEY"):
                st.caption("地址不变时，密钥留空保留。")
            st.divider()
            st.markdown("**模型**")
            model_name = st.text_input("模型名称 *", key="config_model_name", max_chars=200, label_visibility="collapsed",
                placeholder="填写服务账号可用的模型标识", help="模型标识需与服务商控制台一致，不自动假定你拥有某一模型的权限。")
            if provider.documentation:
                st.markdown(f"[查看 {provider.name} 的官方接口文档]({provider.documentation})")
            options = _request_options(values)
            st.caption("保存到本机，不调用模型。")
            submitted = st.form_submit_button("保存配置", type="primary", width="stretch")
        if submitted:
            try:
                candidate = replace(current, mode="real", model_base_url=base_url.strip(), model_name=model_name.strip(),
                    model_api_key=resolve_api_key(base_url, api_key, values), **options)
                save_model_settings(candidate)
            except AssistantError as error:
                st.error(str(error))
            else:
                for key in ("analysis_run", "teacher_history", "teacher_confirmation", "input_signature",
                            "batch_papers", "batch_active", "batch_context"):
                    st.session_state.pop(key, None)
                for key in list(st.session_state):
                    if key.startswith("cloud_ack_"):
                        st.session_state.pop(key, None)
                st.session_state["configuration_success"] = True
                st.rerun()

    with guide_area:
        st.subheader("配置要求")
        st.markdown(
            "1. 选择服务商，自动填写 API 地址。\n"
            "2. 从服务控制台复制密钥和模型标识。\n"
            "3. 保存后返回评阅。"
        )
        with st.expander("配置帮助", expanded=False):
            st.caption(provider.note)
            st.markdown(
                "- 地址需兼容 Chat Completions，远程服务使用 HTTPS；不是聊天网页地址。\n"
                "- 密钥不加 Bearer，换地址需重新填写；模型须属于当前账号。\n"
                "- 配置以明文保存在本机 .env，请勿分享。预设不保证服务权限或额度。"
            )
        controlled = [name for name in MODEL_FIELDS if name in os.environ]
        if controlled:
            st.info("以下字段由系统环境变量提供，优先于网页保存的 .env：" + "、".join(controlled)
                + "。如需更换，请修改或取消启动环境中的变量，再重新启动应用。")

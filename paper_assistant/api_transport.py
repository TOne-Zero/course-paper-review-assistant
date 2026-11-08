"""可替换 HTTP 传输；兼容 Chat Completions，不记录密钥、正文或响应体。"""

import json
import logging
import re
import socket
import ssl
import time
from urllib.parse import urlsplit, quote

import httpx

from paper_assistant.config import Settings
from paper_assistant.schemas import AssistantError
from paper_assistant.stream_response import read_response
from paper_assistant.model_protocols import protocol_for, endpoint_for, request_data


class ModelCallError(AssistantError):
    pass


class OutputTruncatedError(ModelCallError):
    pass


def connection_error_message(error):
    """从异常类型区分故障，不回显URL、请求头或底层错误全文。"""
    chain, visited = [], set()
    while error is not None and id(error) not in visited:
        visited.add(id(error)); chain.append(error)
        error = error.__cause__ or error.__context__
    if any(isinstance(item, PermissionError) or getattr(item, 'winerror', None) == 10013 for item in chain):
        return '当前应用进程的网络访问被系统阻止。请停止旧服务，使用“启动应用.cmd”重新启动后测试。'
    if any(isinstance(item, ssl.SSLCertVerificationError) for item in chain):
        return '模型服务的HTTPS证书校验失败，请检查系统时间、证书或校园网络认证。'
    if any(isinstance(item, socket.gaierror) for item in chain):
        return '无法解析模型服务域名，请检查API地址、DNS或校园网络连接。'
    if any(isinstance(item, ConnectionRefusedError) for item in chain):
        return '模型服务拒绝连接，请检查服务是否启动以及地址端口是否正确。'
    if any(isinstance(item, httpx.ProxyError) for item in chain):
        return '代理连接失败，请检查本机网络或代理服务。'
    return '无法连接模型服务，请检查API地址、网络和服务状态。'


def validate_api_settings(settings: Settings) -> str:
    missing = [name for name, value in (("MODEL_API_KEY", settings.model_api_key), ("MODEL_NAME", settings.model_name),
                                        ("MODEL_BASE_URL", settings.model_base_url)) if not value]
    if missing:
        raise AssistantError("模型服务尚未配置，缺少：" + "、".join(missing) + "。请完成模型服务配置。")
    if any(ord(char) < 32 or ord(char) == 127 for char in settings.model_base_url + settings.model_name):
        raise AssistantError("服务地址或模型名称含有无效控制字符，请检查配置。")
    try:
        parts = urlsplit(settings.model_base_url)
        local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parts.scheme not in {"https", "http"} or not parts.hostname or (parts.scheme == "http" and not local)
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError
        _ = parts.port
    except ValueError:
        raise AssistantError("MODEL_BASE_URL 须为 HTTPS API 地址（本机服务可用 HTTP），不能含账号、密钥参数或片段。") from None
    if (not settings.model_api_key.isascii() or any(ord(char) < 32 or ord(char) == 127 for char in settings.model_api_key)
            or len(settings.model_name) > 200):
        raise AssistantError("模型或密钥配置格式无效，请检查本地环境变量。")
    if not 1 <= settings.model_timeout_seconds <= 120 or not 1 <= settings.model_max_calls <= 100:
        raise AssistantError("请求超时须为 1–120 秒，最大调用次数须为 1–100。")
    if settings.model_response_format not in {"json_schema", "json_object", "none"}:
        raise AssistantError("MODEL_RESPONSE_FORMAT 须为 json_schema、json_object 或 none。")
    if settings.model_token_parameter not in {"max_tokens", "max_completion_tokens"}:
        raise AssistantError("MODEL_TOKEN_PARAMETER 仅支持 max_tokens 或 max_completion_tokens。")
    if not 1 <= settings.model_chunk_characters <= settings.model_batch_characters <= 32000:
        raise AssistantError("分段字数与批次字数须满足：1 ≤ 分段字数 ≤ 批次字数 ≤ 32000。")
    if settings.model_max_output_tokens < 0 or min(settings.model_max_prompt_characters, settings.model_max_synthesis_characters) <= 0:
        raise AssistantError("输出token设置不能为负数（0表示不传上限）；提示和合成字数必须大于0。")
    return endpoint_for(settings.model_base_url, settings.model_name, protocol_for(settings.model_base_url))


def service_label(settings: Settings) -> str:
    try:
        parts = urlsplit(settings.model_base_url)
        if parts.hostname and not parts.username and not parts.password and not parts.query:
            return parts.hostname + (f":{parts.port}" if parts.port else "")
    except ValueError:
        pass
    return "未配置或无效地址"


class HTTPChatTransport:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None, on_stream=None, request_state=None):
        self.settings = settings
        self.endpoint = validate_api_settings(settings)
        self.transport = transport
        self.on_stream = on_stream
        self.protocol = protocol_for(settings.model_base_url)
        self.response_format = settings.model_response_format
        self.use_stream = bool(on_stream)
        self.token_parameter = settings.model_token_parameter
        self.native_max = 65536
        self.native_max_checked = False
        self.request_state = request_state if request_state is not None else {'posts':0}

    @property
    def requests_sent(self):
        return self.request_state['posts']

    def _headers(self):
        key=self.settings.model_api_key
        if self.protocol=='anthropic':
            return {'x-api-key':key,'Authorization':'Bearer '+key,'anthropic-version':'2023-06-01'}
        if self.protocol=='gemini':return {'x-goog-api-key':key}
        return {'Authorization':'Bearer '+key}

    def _compatibility(self, response, deadline):
        """只在明确的参数/路径拒绝时调整；不把认证、额度错误当作兼容重试。"""
        if response.status_code not in (400,404,405,422):return False
        data=bytearray()
        for block in response.iter_bytes():
            if time.monotonic()>=deadline:raise TimeoutError()
            data.extend(block)
            if len(data)>65536:return False
        detail=bytes(data).decode('utf-8',errors='replace').lower()
        unsupported=any(term in detail for term in ('not support','unsupported','unknown','unrecognized','not allowed','not permitted','supported values','must be one of','invalid response_format type','not implemented','not recognized','不支持','未知参数'))
        unsupported=unsupported or ('json_schema' in detail and any(term in detail for term in ('only','supported','invalid')))
        if response.status_code in (400,422) and unsupported:
            if any(field in detail for field in ('response_format','json_schema','json_object','responsemimetype','text.format')) and self.response_format!='none':
                self.response_format='json_object' if self.response_format=='json_schema' else 'none'
                return True
            if 'stream' in detail and self.use_stream:
                self.use_stream=False;return True
            if self.settings.model_max_output_tokens and self.protocol=='chat' and self.token_parameter=='max_tokens' and 'max_tokens' in detail:
                self.token_parameter='max_completion_tokens';return True
        # Anthropic原生协议要求max_tokens：优先模型元数据，否则仅采用服务明确声明的上限。
        if response.status_code in (400,422) and self.protocol=='anthropic' and not self.settings.model_max_output_tokens and 'max_tokens' in detail:
            match=re.search(r'(?:at most|maximum(?:\s+is)?|less than or equal to|<=|must be\s*<=)\s*[:=]?\s*(\d+)',detail)
            if match and 128<=int(match[1])<self.native_max:
                self.native_max=int(match[1]);return True
        base=self.settings.model_base_url.rstrip('/')
        if response.status_code in (404,405) and self.protocol=='chat' and not any(term in detail for term in ('model_not_found','model not found','invalid model')):
            path=urlsplit(base).path
            if not path and self.endpoint==base+'/chat/completions':
                self.endpoint=base+'/v1/chat/completions';return True
            # 仅同源切换协议路径；用户显式填完整接口时不猜另一条路径。
            if not path.endswith(('/chat/completions','/chat')):
                root=self.endpoint.removesuffix('/chat/completions')
                self.protocol='responses';self.endpoint=root+'/responses';return True
        return False

    def complete(self, messages: list[dict], schema: dict) -> str:
        if len(json.dumps(messages, ensure_ascii=False)) > self.settings.model_max_prompt_characters:
            raise ModelCallError("提示文本超过配置上限；未截断或发送本次内容，请调整分段预算。")
        if self.on_stream:
            self.on_stream({'kind': 'start'})
        # 不使用或输出第三方库的请求/响应调试日志。
        logging.getLogger("httpx").disabled = True
        logging.getLogger("httpcore").disabled = True
        deadline = time.monotonic() + self.settings.model_timeout_seconds
        try:
            with httpx.Client(timeout=self.settings.model_timeout_seconds, follow_redirects=False,
                              trust_env=False, transport=self.transport) as client:
                if self.protocol=='anthropic' and not self.settings.model_max_output_tokens and not self.native_max_checked:
                    self.native_max_checked=True
                    metadata_url=self.endpoint.removesuffix('/messages')+'/models/'+quote(self.settings.model_name,safe='')
                    with client.stream('GET',metadata_url,headers=self._headers(),timeout=min(10,self.settings.model_timeout_seconds)) as metadata:
                        data=bytearray()
                        for block in metadata.iter_bytes():
                            if time.monotonic()>=deadline:raise TimeoutError()
                            data.extend(block)
                            if len(data)>65536:break
                        if metadata.status_code==200 and len(data)<=65536:
                            try:
                                limit=json.loads(data).get('max_tokens')
                                if type(limit) is int and 128<=limit<=2_000_000:self.native_max=limit
                            except (ValueError,AttributeError):pass
                for attempt in range(6):
                    if time.monotonic()>=deadline:raise TimeoutError()
                    if self.requests_sent>=self.settings.model_max_calls:
                        raise ModelCallError('本轮模型请求次数已达到限制；未跳过失败步骤或补造结果，请检查接口兼容性后重新评阅。')
                    body=request_data(self.settings,messages,schema,self.protocol,stream=self.use_stream,response_format=self.response_format,token_parameter=self.token_parameter,native_max=self.native_max)
                    endpoint=self.endpoint
                    if self.protocol=='gemini':endpoint=endpoint_for(self.settings.model_base_url,self.settings.model_name,'gemini',self.use_stream)
                    self.request_state['posts']+=1
                    with client.stream('POST',endpoint,headers=self._headers(),json=body,timeout=max(.1,deadline-time.monotonic())) as response:
                      if response.status_code >= 300:
                        if attempt<5 and self._compatibility(response,deadline):continue
                        messages_by_status = {401: "API 认证失败，请检查本地密钥。", 403: "API 服务拒绝访问。",
                                              400: 'API 请求被拒绝（HTTP 400），请检查模型标识与服务兼容性。',
                                              404: 'API 接口不存在（HTTP 404），请核对API根地址和模型名称。',
                                              429: "API 限流或额度不足，请稍后重试。", 413: "服务认为文本过长，请调整分段配置。",
                                              408: "API 请求超时。", 504: "API 服务超时。"}
                        raise ModelCallError(messages_by_status.get(response.status_code, f"API 调用失败（HTTP {response.status_code}）；未采用响应内容。"))
                      payload = read_response(response, self.settings.model_api_key, self.on_stream, deadline)
                      break
            choice = payload["choices"][0]
            if choice.get('finish_reason') == 'length':
                label = f'当前上限（{self.settings.model_max_output_tokens} token）' if self.settings.model_max_output_tokens else '服务商的输出上限（应用未设置输出长度限制）'
                if self.protocol=='anthropic' and not self.settings.model_max_output_tokens:
                    label=f'原生接口要求的输出上限（{self.native_max} token）'
                raise OutputTruncatedError(f'模型输出达到{label}，未采用不完整评分。')
            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                raise ModelCallError("模型拒答或输出被截断，未采用本次结果。请检查模型配置、文本预算和输出上限。")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ModelCallError("模型没有返回有效文本结果。")
            if len(self.settings.model_api_key) >= 8 and self.settings.model_api_key in content:
                raise ModelCallError("服务响应包含敏感配置信息，已阻止采用。")
            return content
        except ModelCallError:
            raise
        except AssistantError as error:
            raise ModelCallError(str(error)) from None
        except (httpx.TimeoutException, TimeoutError):
            raise ModelCallError("API 请求超时，未伪造或补齐结果；可稍后重试。") from None
        except httpx.HTTPError as error:
            raise ModelCallError(connection_error_message(error)) from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeError):
            raise ModelCallError("模型服务响应格式无效，未采用结果。") from None

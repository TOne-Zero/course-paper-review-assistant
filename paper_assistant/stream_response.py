"""消费Chat Completions流，仅发布生成片段和分析进度，不公开内部推理全文。"""
import json
import time

from paper_assistant.schemas import AssistantError
from paper_assistant.model_protocols import normalize_payload, text_parts


def read_response(response, key, emit=None, deadline=None):
    def check_time():
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError()
    if 'text/event-stream' not in response.headers.get('content-type', '').lower():
        data = bytearray()
        for block in response.iter_bytes():
            check_time()
            data.extend(block)
            if len(data) > 16 * 1024 * 1024:
                raise AssistantError('响应超过本机单次读取容量，已停止读取；未采用不完整结果。')
        if 'text/html' in response.headers.get('content-type', '').lower() or bytes(data).lstrip().lower().startswith((b'<!doctype html', b'<html')):
            raise AssistantError('当前地址返回的是网页，不是模型API。请填写服务商的API根地址（通常包含/v1），不要填写网站首页。')
        if bytes(data).lstrip().startswith((b'data:',b'event:')):
            lines = bytes(data).decode('utf-8-sig').splitlines()
        else:
            payload = normalize_payload(json.loads(bytes(data)))
            if emit:
                text = payload['choices'][0]['message']['content']
                if isinstance(text, str) and (not key or key not in text):
                    emit({'kind': 'output', 'text': text, 'streaming': False, 'final': True})
            return payload
    else:
        lines = response.iter_lines()
    content, reasoning_count, finish, refusal, size = '', 0, None, False, 0
    event_lines = []
    anthropic_seen, anthropic_stopped = False, False

    def event(lines):
        nonlocal content, reasoning_count, finish, refusal, anthropic_seen, anthropic_stopped
        data = '\n'.join(lines)
        if data.strip() == '[DONE]':
            return
        packet = json.loads(data)
        kind = packet.get('type','')
        if kind.startswith(('message_','content_block_')):anthropic_seen=True
        if kind=='error' or 'error' in packet:
            raise AssistantError('模型服务在生成过程中返回错误，本次结果未采用；可稍后重试。')
        # Responses、Anthropic、Gemini均转为同一套增量事件；推理仅累计数量。
        if kind=='response.output_text.delta':
            packet={'choices':[{'delta':{'content':packet['delta']}}]}
        elif kind.startswith('response.reasoning') and kind.endswith('.delta'):
            packet={'choices':[{'delta':{'reasoning_content':packet.get('delta','')}}]}
        elif kind in ('response.completed','response.incomplete','response.failed'):
            final=normalize_payload({'output':[],**packet['response']})['choices'][0]
            if not content:content=final['message']['content']
            finish=final['finish_reason'];refusal=bool(final['message']['refusal']);return
        elif kind=='content_block_delta':
            delta=packet.get('delta',{})
            packet={'choices':[{'delta':{'content':delta.get('text',''),'reasoning_content':delta.get('thinking','')}}]}
        elif kind=='content_block_start':
            block=packet.get('content_block',{})
            packet={'choices':[{'delta':{'content':block.get('text','') if block.get('type')=='text' else ''}}]}
        elif kind=='message_delta':
            reason=packet.get('delta',{}).get('stop_reason')
            finish='stop' if reason in ('end_turn','stop_sequence') else 'length' if reason=='max_tokens' else None
            return
        elif kind=='message_stop':
            anthropic_stopped=True
            return
        elif 'candidates' in packet:
            candidate=packet['candidates'][0]
            parts=candidate.get('content',{}).get('parts',[])
            delta={'content':''.join(p.get('text','') for p in parts if not p.get('thought')),
                   'reasoning_content':''.join(p.get('text','') for p in parts if p.get('thought'))}
            reason=candidate.get('finishReason')
            packet={'choices':[{'delta':delta,'finish_reason':'stop' if reason=='STOP' else 'length' if reason=='MAX_TOKENS' else None}]}
            if reason and reason not in ('STOP','MAX_TOKENS'):refusal=True
        choices = packet.get('choices', [])
        if not choices:
            return
        choice = choices[0]
        delta = choice.get('delta') or choice.get('message') or {}
        if delta.get('refusal'):
            refusal = True
        reasoning = delta.get('reasoning_content') or delta.get('reasoning') or ''
        if isinstance(reasoning, str) and reasoning:
            reasoning_count += len(reasoning)
            if emit:
                emit({'kind': 'reasoning', 'characters': reasoning_count, 'streaming': True})
        text = text_parts(delta.get('content') or '')
        if text:
            content += text
            if key and key in content:
                raise AssistantError('服务响应包含敏感配置信息，已阻止采用。')
            # 留下一个密钥长度的尾部，避免密钥跨流片段时先暴露前半段。
            preview = content[:-len(key)] if key and len(content) > len(key) else '' if key else content
            if emit:
                emit({'kind': 'output', 'text': preview, 'streaming': True, 'final': False})
        if choice.get('finish_reason') is not None:
            finish = choice['finish_reason']

    for line in lines:
        check_time()
        size += len(line.encode('utf-8'))
        if size > 16 * 1024 * 1024:
            raise AssistantError('响应超过本机单次读取容量，已停止读取；未采用不完整结果。')
        if not line:
            if event_lines:
                event(event_lines); event_lines = []
        elif line.startswith('data:'):
            event_lines.append(line[5:].lstrip(' '))
    if event_lines:
        event(event_lines)
    if anthropic_seen and not anthropic_stopped:finish=None
    if key and key in content:
        raise AssistantError('服务响应包含敏感配置信息，已阻止采用。')
    if emit and finish == 'stop' and not refusal:
        emit({'kind': 'output', 'text': content, 'streaming': True, 'final': True})
    return {'choices': [{'finish_reason': finish, 'message': {'content': content, 'refusal': refusal}}]}

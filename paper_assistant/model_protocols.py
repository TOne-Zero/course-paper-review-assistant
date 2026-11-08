"""常见文本模型HTTP协议转换，统一为现有的已结束消息结构。"""
from urllib.parse import quote, urlsplit


def protocol_for(url):
    parts = urlsplit(url)
    path = parts.path.rstrip('/')
    if path.endswith('/responses'):
        return 'responses'
    if path.endswith('/messages') or parts.hostname == 'api.anthropic.com' or 'anthropic' in path.split('/'):
        return 'anthropic'
    if ':generateContent' in path or ':streamGenerateContent' in path or path.endswith('/v1beta') or (parts.hostname == 'generativelanguage.googleapis.com' and '/openai' not in path):
        return 'gemini'
    return 'chat'


def endpoint_for(base, model, protocol, stream=False):
    base = base.rstrip('/')
    if protocol == 'responses':
        return base if base.endswith('/responses') else base+'/responses'
    if protocol == 'anthropic':
        return base if base.endswith('/messages') else base+('/messages' if base.endswith('/v1') else '/v1/messages')
    if protocol == 'gemini':
        suffix = ':streamGenerateContent?alt=sse' if stream else ':generateContent'
        if '/models/' in base:
            return base.split('/models/', 1)[0]+'/models/'+quote(model.removeprefix('models/'),safe='')+suffix
        return base+('' if base.endswith(('/v1beta','/v1')) else '/v1beta')+'/models/'+quote(model.removeprefix('models/'),safe='')+suffix
    if base.endswith('/chat/completions'):
        return base
    return base+('/completions' if base.endswith('/chat') else '/chat/completions')


def request_data(settings, messages, schema, protocol, *, stream, response_format, token_parameter, native_max=65536):
    mode = response_format
    if protocol == 'anthropic':
        return {'model':settings.model_name, 'messages':[m for m in messages if m['role']!='system'],
                'system':'\n\n'.join(m['content'] for m in messages if m['role']=='system'),
                'stream':stream, 'max_tokens':settings.model_max_output_tokens or native_max}
    if protocol == 'gemini':
        body = {'contents':[{'role':'model' if m['role']=='assistant' else 'user','parts':[{'text':m['content']}]} for m in messages if m['role']!='system']}
        system = '\n\n'.join(m['content'] for m in messages if m['role']=='system')
        if system:body['systemInstruction']={'parts':[{'text':system}]}
        options = {}
        if mode != 'none': options['responseMimeType']='application/json'
        if settings.model_max_output_tokens:options['maxOutputTokens']=settings.model_max_output_tokens
        if options:body['generationConfig']=options
        return body
    body = {'model':settings.model_name, 'stream':stream}
    if protocol == 'responses':
        body.update(input=messages,store=False)
        if settings.model_max_output_tokens:body['max_output_tokens']=settings.model_max_output_tokens
        if mode!='none':
            body['text']={'format':{'type':'json_object'} if mode=='json_object' else {'type':'json_schema','name':'paper_evaluation','strict':True,'schema':schema}}
    else:
        body['messages']=messages
        if settings.model_max_output_tokens:body[token_parameter]=settings.model_max_output_tokens
        if mode=='json_object':body['response_format']={'type':'json_object'}
        elif mode=='json_schema':body['response_format']={'type':'json_schema','json_schema':{'name':'paper_evaluation','strict':True,'schema':schema}}
    return body


def text_parts(content):
    if isinstance(content,str):return content
    if not isinstance(content,list):raise ValueError()
    output=[]
    for part in content:
        if not isinstance(part,dict):raise ValueError()
        if part.get('type') in ('text','output_text') and isinstance(part.get('text'),str):output.append(part['text'])
    return ''.join(output)


def envelope(text,finish,refusal=False):
    return {'choices':[{'finish_reason':finish,'message':{'content':text,'refusal':refusal}}]}


def normalize_payload(payload):
    if not isinstance(payload,dict):raise ValueError()
    if 'choices' in payload:
        choice=payload['choices'][0]
        message=choice['message']
        return envelope(text_parts(message['content']),choice.get('finish_reason'),message.get('refusal',False))
    if payload.get('type')=='message' and 'content' in payload:
        reason=payload.get('stop_reason')
        return envelope(text_parts(payload['content']), 'stop' if reason in ('end_turn','stop_sequence') else 'length' if reason=='max_tokens' else None)
    if 'output' in payload:
        output=[]; refusal=False
        for item in payload['output']:
            if item.get('type')=='message':
                output.append(text_parts(item.get('content',[])))
                refusal=refusal or any(p.get('type')=='refusal' for p in item.get('content',[]))
        status=payload.get('status')
        reason=payload.get('incomplete_details') or {}
        return envelope(''.join(output),'stop' if status=='completed' else 'length' if status=='incomplete' and reason.get('reason')=='max_output_tokens' else None,refusal)
    if 'candidates' in payload:
        candidate=payload['candidates'][0]
        parts=candidate.get('content',{}).get('parts',[])
        text=''.join(p['text'] for p in parts if isinstance(p.get('text'),str) and not p.get('thought'))
        reason=candidate.get('finishReason')
        return envelope(text,'stop' if reason=='STOP' else 'length' if reason=='MAX_TOKENS' else None,reason in ('SAFETY','RECITATION','BLOCKLIST','PROHIBITED_CONTENT'))
    raise ValueError()

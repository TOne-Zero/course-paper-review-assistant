import json
import unittest
from dataclasses import replace

import httpx

from paper_assistant.api_transport import HTTPChatTransport, ModelCallError, OutputTruncatedError
from paper_assistant.config import Settings
from paper_assistant.validator import ModelJSONError, parse_model_json
from tests.api_responses import envelope


def sse(*packets):
    return ''.join('data: '+json.dumps(p,ensure_ascii=False)+'\n\n' for p in packets).encode()


class APICompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.settings=Settings(mode='real',model_api_key='compat-test-secret',model_name='test-model',model_base_url='https://unit.invalid/v1')
        self.messages=[{'role':'system','content':'Return JSON.'},{'role':'user','content':'Reply OK.'}]

    def call(self,handler,*,url=None,events=None,settings=None):
        config=settings or self.settings
        if url:config=replace(config,model_base_url=url)
        transport=HTTPChatTransport(config,transport=httpx.MockTransport(handler),on_stream=events.append if events is not None else None)
        return transport.complete(self.messages,{'type':'object'}),transport

    def test_json_wrappers_are_removed_without_modifying_the_object(self):
        for text in ('\ufeff  {"x":1} ','```json\n{"x":1}\n```','```JSON {"x":1} ```','<think>private upstream reasoning</think>\n```json\n{"x":1}\n```','以下是JSON结果：\n```json\n{"x":1}\n```'):
            self.assertEqual(parse_model_json(text),{'x':1})
        for text in ('{"x":1,"x":2}','{"nested":{"x":1,"x":2}}','{"x":1}{"x":2}','{"x":NaN}','[1,2]','```json\n{"x":\n```','1 {"x":1}','null {"x":1}'):
            with self.subTest(text=text),self.assertRaises(ModelJSONError):parse_model_json(text)
        # 解析容量与传输容量一致，不能把较长但完整的JSON误报成语法错误。
        value='x'*210000
        self.assertEqual(parse_model_json(json.dumps({'text':value}))['text'],value)

    def test_unsupported_format_and_stream_are_negotiated_then_cached(self):
        bodies=[];events=[]
        def handle(request):
            body=json.loads(request.content);bodies.append(body)
            if 'response_format' in body:return httpx.Response(400,json={'error':{'message':'response_format is not supported'}})
            if body['stream']:return httpx.Response(422,json={'error':{'message':'stream unsupported'}})
            return httpx.Response(200,json=envelope({'reply':'OK'}))
        result,transport=self.call(handle,events=events)
        self.assertEqual(parse_model_json(result),{'reply':'OK'})
        self.assertEqual(len(bodies),3)
        self.assertFalse(events[-1]['streaming'])
        transport.complete(self.messages,{})
        self.assertEqual(len(bodies),4)
        self.assertTrue(all('max_tokens' not in b and 'max_completion_tokens' not in b for b in bodies))

    def test_root_address_v1_discovery_stays_on_the_entered_origin(self):
        paths=[]
        def handle(request):
            paths.append(str(request.url))
            return httpx.Response(200,json=envelope({'reply':'OK'})) if request.url.path=='/v1/chat/completions' else httpx.Response(404,json={'error':'unknown endpoint'})
        result,_=self.call(handle,url='https://unit.invalid')
        self.assertEqual(parse_model_json(result)['reply'],'OK')
        self.assertEqual(paths,['https://unit.invalid/chat/completions','https://unit.invalid/v1/chat/completions'])

    def test_auth_quota_redirect_and_missing_model_do_not_trigger_discovery(self):
        for status,body in ((401,{}),(403,{}),(429,{}),(302,{}),(404,{'error':'model_not_found'})):
            calls=[]
            def handle(request):calls.append(request);return httpx.Response(status,json=body,headers={'Location':'https://other.invalid/'})
            with self.subTest(status=status),self.assertRaises(ModelCallError):self.call(handle)
            self.assertEqual(len(calls),1)

    def test_compatibility_requests_cannot_exceed_the_call_limit(self):
        calls=[]
        def handle(request):
            calls.append(request)
            return httpx.Response(400,json={'error':'response_format unsupported'})
        with self.assertRaises(ModelCallError):self.call(handle,settings=replace(self.settings,model_max_calls=1))
        self.assertEqual(len(calls),1)

    def test_schema_recovery_falls_back_if_provider_only_supports_json_object(self):
        calls=[]
        def handle(request):
            body=json.loads(request.content);calls.append(body)
            if body.get('response_format',{}).get('type')=='json_schema':
                return httpx.Response(400,json={'error':'json_schema invalid, only json_object is supported'})
            return httpx.Response(200,json=envelope({'reply':'OK'}))
        result,_=self.call(handle,settings=replace(self.settings,model_response_format='json_schema'))
        self.assertEqual(parse_model_json(result)['reply'],'OK');self.assertEqual(len(calls),2)

    def test_responses_stream_has_native_body_and_final_completion(self):
        events=[]
        def handle(request):
            body=json.loads(request.content)
            self.assertEqual(request.url.path,'/v1/responses');self.assertIn('input',body);self.assertFalse(body['store'])
            self.assertIn('text',body);self.assertNotIn('max_output_tokens',body)
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=sse(
                {'type':'response.output_text.delta','delta':'{"reply":'},
                {'type':'response.output_text.delta','delta':'"OK"}'},
                {'type':'response.completed','response':{'status':'completed','output':[]}}))
        result,_=self.call(handle,url='https://unit.invalid/v1/responses',events=events)
        self.assertEqual(parse_model_json(result),{'reply':'OK'});self.assertTrue(events[-1]['final'])

    def test_responses_only_gateway_is_discovered_from_a_root(self):
        paths=[]
        def handle(request):
            paths.append(request.url.path)
            if request.url.path.endswith('/responses'):
                return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"reply":"OK"}'}]}]})
            return httpx.Response(404,json={'error':'unknown endpoint'})
        result,_=self.call(handle)
        self.assertEqual(parse_model_json(result)['reply'],'OK')
        self.assertEqual(paths,['/v1/chat/completions','/v1/responses'])

    def test_anthropic_native_max_comes_from_model_metadata_and_thinking_is_private(self):
        events=[]
        def handle(request):
            self.assertEqual(request.headers['x-api-key'],self.settings.model_api_key)
            if request.method=='GET':return httpx.Response(200,json={'max_tokens':96000})
            body=json.loads(request.content);self.assertEqual(body['max_tokens'],96000)
            self.assertEqual(body['system'],'Return JSON.');self.assertEqual(len(body['messages']),1)
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=sse(
                {'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'upstream private thought'}},
                {'type':'content_block_delta','delta':{'type':'text_delta','text':'{"reply":"OK"}'}},
                {'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}))
        result,_=self.call(handle,url='https://unit.invalid/v1/messages',events=events)
        self.assertEqual(parse_model_json(result)['reply'],'OK')
        self.assertNotIn('upstream private thought',json.dumps(events))

    def test_gemini_native_stream_and_safety_finish(self):
        events=[]
        def handle(request):
            self.assertTrue(request.url.path.endswith('/models/test-model:streamGenerateContent'))
            self.assertEqual(request.url.params['alt'],'sse');self.assertEqual(request.headers['x-goog-api-key'],self.settings.model_api_key)
            body=json.loads(request.content);self.assertIn('systemInstruction',body)
            self.assertNotIn('maxOutputTokens',body['generationConfig'])
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=sse(
                {'candidates':[{'content':{'parts':[{'text':'private Gemini thought','thought':True},{'text':'{"reply":"OK"}'}]},'finishReason':'STOP'}]}))
        result,_=self.call(handle,url='https://unit.invalid/v1beta/models/test-model:generateContent',events=events)
        self.assertEqual(parse_model_json(result)['reply'],'OK');self.assertNotIn('private Gemini thought',json.dumps(events))

    def test_native_nonstream_blocks_and_refusals(self):
        for url,payload in (
            ('https://unit.invalid/v1/messages',{'type':'message','stop_reason':'end_turn','content':[{'type':'thinking','thinking':'private'},{'type':'text','text':'{"reply":"OK"}'}]}),
            ('https://unit.invalid/v1beta/models/test-model:generateContent',{'candidates':[{'content':{'parts':[{'text':'{"reply":"OK"}'}]},'finishReason':'STOP'}]}),
            ('https://unit.invalid/v1',{'choices':[{'finish_reason':'stop','message':{'content':[{'type':'text','text':'{"reply":"OK"}'}]}}]})):
            result,_=self.call(lambda request:httpx.Response(200,json=payload),url=url,settings=replace(self.settings,model_max_output_tokens=128))
            self.assertEqual(parse_model_json(result)['reply'],'OK')
        for payload in ({'candidates':[{'content':{'parts':[{'text':'blocked'}]},'finishReason':'SAFETY'}]},
                        {'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]}):
            with self.assertRaises(ModelCallError):self.call(lambda request:httpx.Response(200,json=payload))

    def test_missing_stream_header_and_native_truncation_remain_truthful(self):
        data=sse({'choices':[{'delta':{'content':'{"reply":"OK"}'},'finish_reason':'stop'}]})
        result,_=self.call(lambda request:httpx.Response(200,content=data),events=[])
        self.assertEqual(parse_model_json(result)['reply'],'OK')
        data=sse({'type':'content_block_delta','delta':{'text':'{"x":1}'}},{'type':'message_delta','delta':{'stop_reason':'max_tokens'}},{'type':'message_stop'})
        with self.assertRaises(OutputTruncatedError):self.call(lambda request:httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=data),events=[])
        data=sse({'type':'content_block_delta','delta':{'text':'{"x":1}'}},{'type':'message_delta','delta':{'stop_reason':'end_turn'}})
        with self.assertRaises(ModelCallError):self.call(lambda request:httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=data),events=[])

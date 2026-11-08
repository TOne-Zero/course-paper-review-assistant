import json
import unittest

import httpx

from paper_assistant.api_transport import HTTPChatTransport, ModelCallError, OutputTruncatedError
from paper_assistant.config import Settings


def packet(delta, finish=None):
    return ('data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]}, ensure_ascii=False) + '\n\n').encode('utf-8')


class BytesStream(httpx.SyncByteStream):
    def __init__(self, blocks): self.blocks = blocks
    def __iter__(self): yield from self.blocks


class StreamResponseTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(mode='real', model_api_key='unit-test-secret-key', model_base_url='https://unit.invalid/v1', model_name='test')

    def test_unbounded_request_omits_both_token_fields_and_streams_generation(self):
        events, bodies = [], []
        content = json.dumps({'reason': '研究问题明确，正在生成逐项评价。'*12}, ensure_ascii=False)
        def handle(request):
            bodies.append(json.loads(request.content))
            blocks = [packet({'reasoning_content': 'not-public-internal-reasoning'})]
            blocks += [packet({'content': content[i:i+16]}) for i in range(0, len(content), 16)]
            blocks += [packet({}, 'stop'), b'data: [DONE]\n\n']
            raw = b''.join(blocks)
            return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, stream=BytesStream([raw[i:i+7] for i in range(0, len(raw), 7)]))
        output = HTTPChatTransport(self.settings, transport=httpx.MockTransport(handle), on_stream=events.append).complete([], {})
        self.assertEqual(output, content)
        self.assertTrue(bodies[0]['stream'])
        self.assertNotIn('max_tokens', bodies[0]); self.assertNotIn('max_completion_tokens', bodies[0])
        self.assertGreater(len([e for e in events if e['kind'] == 'output' and e['text']]), 2)
        self.assertTrue(any(e['kind'] == 'reasoning' and e['characters'] > 0 for e in events))
        self.assertNotIn('not-public-internal-reasoning', json.dumps(events))

    def test_missing_finish_and_provider_length_do_not_become_valid_output(self):
        for finish, expected in ((None, ModelCallError), ('length', OutputTruncatedError)):
            transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, content=packet({'content': '{"reason":"partial"}'}, finish)))
            with self.subTest(finish=finish), self.assertRaises(expected):
                HTTPChatTransport(self.settings, transport=transport, on_stream=lambda event: None).complete([], {})

    def test_secret_split_between_packets_never_reaches_preview(self):
        events = []
        key = self.settings.model_api_key
        data = packet({'content': 'prefix '*20+key[:10]}) + packet({'content': key[10:]}) + packet({}, 'stop')
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, content=data))
        with self.assertRaises(ModelCallError):
            HTTPChatTransport(self.settings, transport=transport, on_stream=events.append).complete([], {})
        self.assertNotIn(key, json.dumps(events))

    def test_nonstreaming_provider_fallback_is_explicit(self):
        events = []
        payload = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        self.assertEqual(HTTPChatTransport(self.settings, transport=transport, on_stream=events.append).complete([], {}), '{"ok":true}')
        self.assertFalse(events[-1]['streaming'])

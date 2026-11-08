import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
import copy
from unittest.mock import patch
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx

from paper_assistant.config import Settings
from paper_assistant.web_service import WebApplication, make_server
from tests.api_responses import envelope, valid_response
from tests.pdf_fixture import make_pdf
from tests.word_fixture import make_docx
from paper_assistant.schemas import AssistantError


def criteria_payload(rubric):
    return {'id': rubric['id'], 'expectedVersion': rubric['version'], 'confirm': True,
            'dimensions': [{'id': d['id'], 'name': d['name'], 'weight': d['max_score'],
                            'detailText': '；'.join(d['checklist']), 'detailScores': d['checklist_scores']}
                           for d in rubric['dimensions']]}


class WebServiceTests(unittest.TestCase):
    def test_mixed_word_pdf_upload_runs_through_same_review_and_export(self):
        converted=make_pdf(texts=['原创虚构测试：此处只验证Word分页与模型链路。研究问题、方法和表格内容用于受控检查，不代表真实研究。'*5])
        with patch('paper_assistant.document_parser.convert_word_to_pdf',return_value=converted):
            result=self.client.post('/api/upload',files=[('files',('one.pdf',make_pdf(),'application/pdf')),('files',('two.docx',make_docx(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),('files',('three.doc',bytes.fromhex('D0CF11E0A1B11AE1')+b'fixture','application/msword'))])
        result.raise_for_status();self.assertEqual(len(result.json()['papers']),3)
        self.client.post('/api/start',json={'consent':True}).raise_for_status()
        state=self.wait_done();self.assertTrue(all(p['totalScore']==80 for p in state['papers']))
        self.assertEqual([p['report']['document']['source'] for p in state['papers']],['pdf','docx','doc'])
        archive=zipfile.ZipFile(io.BytesIO(self.client.get('/api/reports').content))
        self.assertEqual(sum(n.endswith('.md') for n in archive.namelist()),3)

    def test_connection_probe_accepts_plain_ok_without_changing_saved_settings(self):
        self.test_reply='OK'
        response=self.client.post('/api/model/test',json={})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['reply'],'OK')
        self.assertEqual(self.app.model_settings,self.settings)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []
        self.reject_model = False
        self.corrupt_checks = False
        self.test_reply = {'reply': 'OK'}
        owner = self
        class ModelHandler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                content = self.rfile.read(int(self.headers['Content-Length']))
                owner.calls.append(content)
                if owner.reject_model:
                    self.send_response(401); self.end_headers(); return
                body = json.loads(content)
                if 'dimension' in body['messages'][1]['content']:
                    result = valid_response(SimpleNamespace(content=content))
                else:
                    result = owner.test_reply
                if owner.corrupt_checks and 'check_scores' in result:
                    result.pop('check_scores')
                data = json.dumps(envelope(result)).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        self.model_server = ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
        self.model_thread = threading.Thread(target=self.model_server.serve_forever, daemon=True); self.model_thread.start()
        self.settings = Settings(mode='real', model_base_url=f'http://127.0.0.1:{self.model_server.server_port}/v1', model_name='controlled-test-only', model_api_key='test-secret-never-return')
        self.app = WebApplication(env_path=Path(self.temp.name)/'.env', settings=self.settings)
        self.server = make_server(self.app, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = httpx.Client(base_url=self.url, trust_env=False, headers={'X-Paper-Request':'1','X-Review-Mode':'real'})
        self.client.get('/api/state').raise_for_status()

    def tearDown(self):
        self.client.close(); self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.app.executor.shutdown(wait=True)
        self.model_server.shutdown(); self.model_server.server_close(); self.model_thread.join(); self.temp.cleanup()

    def upload(self, names=('paper.pdf',)):
        return self.client.post('/api/upload', files=[('files',(name,make_pdf(),'application/pdf')) for name in names])

    def wait_done(self):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            state=self.client.get('/api/state').json()
            if not state['running']: return state
            time.sleep(.03)
        self.fail('worker did not finish')

    def test_real_http_pipeline_review_export_and_clear(self):
        self.assertEqual(self.upload().status_code,200)
        response=self.client.post('/api/start',json={'consent':False})
        self.assertEqual(response.status_code,400); self.assertEqual(self.calls,[])
        self.client.post('/api/start',json={'consent':True}).raise_for_status()
        state=self.wait_done(); paper=state['papers'][0]
        self.assertFalse(paper['report']['is_mock']); self.assertEqual(len(self.calls),7)
        self.assertEqual(paper['totalScore'],80); self.assertEqual(paper['pages'][0]['number'],1)
        self.assertTrue(paper['report']['dimensions'][0]['evidence'][0]['verified'])
        self.assertNotIn(self.settings.model_api_key,json.dumps(state))
        self.client.post('/api/reviews/'+paper['id'],json={'evaluationId':paper['report']['evaluation_id'],'scores':[90]*7,'note':'原文核对后调整。'}).raise_for_status()
        state=self.client.get('/api/state').json();self.assertEqual(state['papers'][0]['totalScore'],90)
        self.assertTrue(state['papers'][0]['reviewed'])
        with zipfile.ZipFile(io.BytesIO(self.client.get('/api/reports').content)) as archive:
            data=json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('.json') and n!='批次清单.json')))
            self.assertFalse(data['is_mock']);self.assertEqual(data['total_score'],80)
            self.assertEqual(data['teacher_review']['total_score'],90)
            self.assertEqual(len(data['teacher_review']['history']),7)
        self.client.post('/api/clear',json={}).raise_for_status()
        self.assertEqual(self.client.get('/api/state').json()['papers'],[])

    def test_failed_model_preserves_nulls_and_never_falls_back(self):
        self.upload().raise_for_status();self.reject_model=True
        self.client.post('/api/start',json={'consent':True}).raise_for_status();paper=self.wait_done()['papers'][0]
        self.assertFalse(paper['report']['is_mock']);self.assertIsNone(paper['totalScore'])
        self.assertTrue(all(v is None for v in paper['scores']));self.assertTrue(paper['report']['diagnostics'])
        self.reject_model=False
        self.client.post('/api/start',json={'consent':True}).raise_for_status()
        self.assertEqual(self.wait_done()['papers'][0]['totalScore'],80)

    def test_pause_waits_for_current_paper_and_blocks_mutations(self):
        started=threading.Event();release=threading.Event();original=self.app.analyzer
        def controlled(*args,**kwargs):
            started.set();release.wait(5);return original(*args,**kwargs)
        self.app.analyzer=controlled
        self.upload(('one.pdf','two.pdf')).raise_for_status()
        self.client.post('/api/start',json={'consent':True}).raise_for_status();self.assertTrue(started.wait(2))
        try:
            self.assertEqual(self.client.post('/api/clear',json={}).status_code,400)
            self.assertEqual(self.client.post('/api/model',json={'url':self.settings.model_base_url,'model':'changed','key':''}).status_code,400)
            self.client.post('/api/pause',json={}).raise_for_status()
        finally:
            release.set()
        state=self.wait_done();self.assertEqual(state['papers'][0]['totalScore'],80)
        self.assertIsNone(state['papers'][1]['report']);self.assertEqual(state['papers'][1]['status'],'queued')

    def test_modes_sessions_and_request_boundary(self):
        self.upload().raise_for_status()
        self.assertEqual(self.client.get('/api/state',headers={'X-Review-Mode':'mock'}).json()['papers'],[])
        with httpx.Client(base_url=self.url,trust_env=False) as other:
            self.assertEqual(other.get('/api/state').json()['papers'],[])
            self.assertEqual(other.post('/api/clear',json={}).status_code,400)
        self.assertEqual(self.client.post('/api/clear',json={},headers={'Origin':'https://outside.example'}).status_code,400)
        self.assertEqual(self.client.get('/api/state',headers={'Host':'outside.example'}).status_code,400)
        self.assertEqual(self.client.post('/api/demo',json={}).status_code,400)

    def test_upload_limits_atomic_validation_and_bad_pdf(self):
        self.assertEqual(self.upload(tuple(f'{i}.pdf' for i in range(11))).status_code,400)
        self.assertEqual(self.client.get('/api/state').json()['papers'],[])
        self.assertEqual(self.client.post('/api/upload',files={'files':('bad.pdf',b'not a PDF')}).status_code,400)
        result=self.client.post('/api/upload',files={'files':('corrupt.pdf',b'%PDF-1.4 broken')})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['papers'][0]['status'],'failed')

    def test_rubric_changes_invalidate_results_and_versions_guard_review(self):
        self.upload().raise_for_status();self.client.post('/api/start',json={'consent':True}).raise_for_status();paper=self.wait_done()['papers'][0]
        self.assertEqual(self.client.post('/api/reviews/'+paper['id'],json={'evaluationId':'old','scores':[80]*7,'note':'x'}).status_code,400)
        self.assertEqual(self.client.post('/api/rubric',json={'id':'course_demo','weights':[10]*7}).status_code,400)
        result=self.client.post('/api/rubric',json={'id':'course_demo','weights':[20,10,20,20,10,10,10]})
        self.assertEqual(result.status_code,200);self.assertIsNone(result.json()['papers'][0]['report'])
        self.assertEqual(result.json()['papers'][0]['status'],'queued')

    def test_config_retains_secret_only_for_same_endpoint_and_tests_connection(self):
        result=self.client.post('/api/model',json={'url':self.settings.model_base_url,'model':self.settings.model_name,'key':''})
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['model']['key'],'')
        self.assertTrue(result.json()['model']['keySaved'])
        self.assertIn('test-secret-never-return',(Path(self.temp.name)/'.env').read_text(encoding='utf-8'))
        result=self.client.post('/api/model',json={'url':'http://127.0.0.1:1/v1','model':'test','key':''})
        self.assertEqual(result.status_code,400);self.assertEqual(self.app.model_settings.model_base_url,self.settings.model_base_url)
        self.assertEqual(self.client.post('/api/model/test',json={}).status_code,200)
        self.assertLessEqual(json.loads(self.calls[-1])['max_tokens'],128)

    def test_mock_uses_real_pdf_without_any_model_request(self):
        self.client.headers['X-Review-Mode']='mock'
        self.client.post('/api/demo',json={}).raise_for_status()
        self.client.post('/api/start',json={}).raise_for_status()
        paper=self.wait_done()['papers'][0]
        self.assertTrue(paper['report']['is_mock']);self.assertEqual(self.calls,[])
        self.assertTrue(paper['pages'][0]['text'])

    def test_draft_connection_returns_reply_without_saving_or_invalidating(self):
        self.upload().raise_for_status(); self.client.post('/api/start', json={'consent': True}).raise_for_status()
        before = self.wait_done(); evaluation = before['papers'][0]['report']['evaluation_id']
        response = self.client.post('/api/model/test', json={'url': self.settings.model_base_url, 'model': 'draft-model', 'key': ''})
        response.raise_for_status(); result = response.json()
        self.assertEqual(result['reply'], 'OK'); self.assertEqual(result['model'], 'draft-model')
        self.assertGreaterEqual(result['elapsedMs'], 0)
        self.assertEqual(self.app.model_settings.model_name, self.settings.model_name)
        self.assertFalse((Path(self.temp.name)/'.env').exists())
        self.assertEqual(self.client.get('/api/state').json()['papers'][0]['report']['evaluation_id'], evaluation)
        self.assertEqual(self.client.post('/api/model/test', json={'url': 'http://127.0.0.1:1/v1', 'model': 'draft', 'key': ''}).status_code, 400)
        self.test_reply = {'reply': ''}
        self.assertEqual(self.client.post('/api/model/test', json={}).status_code, 400)

    def test_live_progress_is_visible_before_final_report(self):
        started, release = threading.Event(), threading.Event()
        original = self.app.analyzer
        def delayed(document, rubric, settings, **kwargs):
            kwargs['progress']('生成维度参考评价：研究问题')
            kwargs['on_stream']({'kind': 'start'})
            kwargs['on_stream']({'kind': 'reasoning', 'characters': 120})
            kwargs['on_stream']({'kind': 'output', 'text': '{"reason":"正在核对研究问题与材料对应关系。"', 'streaming': True, 'final': False})
            started.set(); release.wait(5)
            return original(document, rubric, settings, **kwargs)
        self.app.analyzer = delayed
        self.upload().raise_for_status(); self.client.post('/api/start', json={'consent': True}).raise_for_status()
        self.assertTrue(started.wait(2))
        try:
            paper = self.client.get('/api/state').json()['papers'][0]
            self.assertEqual(paper['status'], 'processing'); self.assertIsNone(paper['report'])
            self.assertEqual(paper['live']['reasoningCharacters'], 120)
            self.assertIn('正在核对研究问题', paper['live']['draft'])
            self.assertNotIn(self.settings.model_api_key, json.dumps(paper))
        finally:
            release.set()
        self.assertEqual(self.wait_done()['papers'][0]['live']['phase'], 'complete')

    def test_all_three_criteria_persist_and_reset_presets_stay_original(self):
        original = self.client.get('/api/state').json()
        for rubric in original['rubrics']:
            payload = criteria_payload(rubric)
            dimension = payload['dimensions'][0]
            dimension['detailText'] = '教师自定义检查点一；教师自定义检查点二'
            dimension['detailScores'] = [6, dimension['weight'] - 6]
            state = self.client.post('/api/rubric', json=payload).json()
            self.assertEqual(state['rubric']['dimensions'][0]['checklist_scores'], dimension['detailScores'])
            self.assertEqual(state['rubric']['dimensions'][0]['checklist'], ['教师自定义检查点一', '教师自定义检查点二'])
            self.assertEqual(state['rubricPresets'], original['rubricPresets'])
            self.assertEqual(self.client.post('/api/rubric', json=payload).status_code, 400)
        restored = WebApplication(env_path=Path(self.temp.name)/'.env', settings=self.settings)
        try:
            for rubric in restored.catalogs['real']:
                self.assertEqual(rubric.dimensions[0].checklist[0], '教师自定义检查点一')
            self.assertEqual(restored.active_ids['real'], original['rubrics'][-1]['id'])
            self.assertNotEqual(restored.catalogs['real'][0], restored.catalogs['mock'][0])
        finally:
            restored.executor.shutdown(wait=True)

    def test_fine_scores_reach_real_model_validation_review_and_zip(self):
        self.upload().raise_for_status()
        rubric = self.client.get('/api/state').json()['rubric']
        payload = criteria_payload(rubric)
        payload['dimensions'][0]['detailScores'] = [6, 5, 4]
        payload['dimensions'][0]['detailText'] = '问题必须具体；概念必须清楚；范围必须合理'
        self.client.post('/api/rubric', json=payload).raise_for_status()
        self.client.post('/api/start', json={'consent': True}).raise_for_status()
        paper = self.wait_done()['papers'][0]
        items = paper['report']['dimensions'][0]['check_scores']
        self.assertEqual([item['max_score'] for item in items], [6, 5, 4])
        self.assertEqual([item['score'] for item in items], [4.8, 4, 3.2])
        sent = json.loads(json.loads(self.calls[0])['messages'][1]['content'])
        self.assertEqual(sent['dimension']['checklist_scores'], [6, 5, 4])
        self.assertIn('问题必须具体', sent['dimension']['checklist'])
        self.client.post('/api/reviews/'+paper['id'], json={'evaluationId': paper['report']['evaluation_id'], 'scores': [90]*7, 'note': '教师独立复核。'}).raise_for_status()
        with zipfile.ZipFile(io.BytesIO(self.client.get('/api/reports').content)) as archive:
            data = json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('.json') and n != '批次清单.json')))
            markdown = archive.read(next(n for n in archive.namelist() if n.endswith('.md'))).decode('utf-8')
            self.assertEqual(data['dimensions'][0]['check_scores'], items)
            self.assertEqual(data['teacher_review']['total_score'], 90)
            self.assertIn('细则初评分', markdown)
            self.assertIn('问题必须具体', markdown)
        payload = criteria_payload(self.client.get('/api/state').json()['rubric'])
        payload['dimensions'][0]['detailText'] = '问题重新明确；概念必须清楚；范围必须合理'
        state = self.client.post('/api/rubric', json=payload).json()
        self.assertIsNone(state['papers'][0]['report'])
        self.assertFalse(state['papers'][0]['reviewed'])

    def test_invalid_criteria_and_disk_failure_leave_results_untouched(self):
        self.upload().raise_for_status(); self.client.post('/api/start', json={'consent': True}).raise_for_status()
        state = self.wait_done(); original = state['papers'][0]['report']['evaluation_id']
        valid = criteria_payload(state['rubric'])
        for invalid in ('total', 'negative', 'boolean', 'precision', 'missing', 'empty', 'stale', 'unconfirmed', 'ids'):
            payload = copy.deepcopy(valid)
            first = payload['dimensions'][0]
            if invalid == 'total': first['detailScores'][0] += 1
            elif invalid == 'negative': first['detailScores'][0] = -1
            elif invalid == 'boolean': first['detailScores'][0] = True
            elif invalid == 'precision': first['detailScores'] = [5.001, 4.999, 5]
            elif invalid == 'missing': first['detailScores'].pop()
            elif invalid == 'empty': first['detailText'] = ''
            elif invalid == 'stale': payload['expectedVersion'] = 'old'
            elif invalid == 'unconfirmed': payload['confirm'] = False
            else: first['id'] = 'other'
            with self.subTest(invalid=invalid):
                self.assertEqual(self.client.post('/api/rubric', json=payload).status_code, 400)
                self.assertEqual(self.client.get('/api/state').json()['papers'][0]['report']['evaluation_id'], original)
        with patch.object(self.app.criteria_store, 'save', side_effect=AssistantError('写入失败')):
            valid['dimensions'][0]['detailScores'] = [6, 5, 4]
            self.assertEqual(self.client.post('/api/rubric', json=valid).status_code, 400)
        self.assertEqual(self.client.get('/api/state').json()['papers'][0]['report']['evaluation_id'], original)

    def test_model_missing_small_scores_is_null_then_retryable(self):
        self.upload().raise_for_status(); self.corrupt_checks = True
        self.client.post('/api/start', json={'consent': True}).raise_for_status()
        paper = self.wait_done()['papers'][0]
        self.assertIsNone(paper['totalScore'])
        self.assertTrue(all(item['score'] is None for item in paper['report']['dimensions'][0]['check_scores']))
        self.assertFalse(paper['report']['is_mock'])
        self.corrupt_checks = False
        self.client.post('/api/start', json={'consent': True}).raise_for_status()
        self.assertEqual(self.wait_done()['papers'][0]['totalScore'], 80)

    def test_other_active_session_blocks_criteria_edit_but_mode_is_separate(self):
        other = self.app.session('a'*64, 'real'); other.running = True
        payload = criteria_payload(self.client.get('/api/state').json()['rubric'])
        payload['dimensions'][0]['detailScores'] = [6, 5, 4]
        try:
            self.assertEqual(self.client.post('/api/rubric', json=payload).status_code, 400)
            self.client.headers['X-Review-Mode'] = 'mock'
            mock_payload = criteria_payload(self.client.get('/api/state').json()['rubric'])
            mock_payload['dimensions'][0]['detailScores'] = [4, 5, 6]
            self.client.post('/api/rubric', json=mock_payload).raise_for_status()
        finally:
            other.running = False


if __name__=='__main__':unittest.main()

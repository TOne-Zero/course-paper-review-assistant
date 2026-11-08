from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import httpx

from paper_assistant.analysis_service import analyze_document
from paper_assistant.api_transport import HTTPChatTransport
from paper_assistant.batch import (MAX_BATCH_FILES, activate_paper, analyze_batch, collect_uploads,
    export_batch, parse_batch, store_active, sync_batch)
from paper_assistant.config import Settings
from paper_assistant.demo import demo_document
from paper_assistant.routes import PRODUCTION_PAGE, SETTINGS_PAGE
from paper_assistant.rubrics import load_rubrics
from paper_assistant.schemas import AssistantError
from tests import test_configuration as configuration
from tests.api_responses import envelope, valid_response
from tests.pdf_fixture import make_pdf


def upload(name, data=b'pdf'):
    return SimpleNamespace(name=name, size=len(data), getvalue=lambda: data)


class BatchStateTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(mode='mock')
        self.rubric = load_rubrics()[0]

    def test_limits_checked_before_reading_and_identical_names_remain_distinct(self):
        with self.assertRaisesRegex(AssistantError, '最多'):
            collect_uploads([upload('x.pdf')] * (MAX_BATCH_FILES + 1))
        large = SimpleNamespace(name='large.pdf', size=26*1024*1024,
            getvalue=lambda: self.fail('Oversized batch read into parser'))
        with self.assertRaisesRegex(AssistantError, '50 MB'):
            collect_uploads([large, large])
        papers = collect_uploads([upload('same.pdf'), upload('same.pdf')])
        self.assertEqual(len({item.key for item in papers}), 2)

    def test_parse_failure_isolated_and_unchanged_files_cached(self):
        papers = collect_uploads([upload('bad.pdf', b'invalid'), upload('good.pdf', make_pdf())])
        snapshots = {item.key: {} for item in papers}
        parse_batch(papers, snapshots, self.settings)
        self.assertIn('parse_error', snapshots[papers[0].key])
        good = snapshots[papers[1].key]['parsed_document']
        self.assertTrue(good.can_analyze)
        with patch('paper_assistant.batch.parse_document') as parser:
            parse_batch(papers, snapshots, self.settings)
        parser.assert_not_called()

    def test_switch_restores_review_and_format_state_then_context_invalidates_scores(self):
        state = {}
        snapshots = sync_batch(state, ['a','b'], 'a', 'context1')
        activate_paper(state, snapshots['a'])
        state.update(analysis_run='run-a', teacher_history=[{'edit':'a'}], format_report='format-a')
        snapshots = sync_batch(state, ['a','b'], 'b', 'context1')
        activate_paper(state, snapshots['b'])
        self.assertNotIn('analysis_run',state)
        state.update(analysis_run='run-b', teacher_history=[])
        snapshots = sync_batch(state, ['a','b'], 'a', 'context1')
        activate_paper(state, snapshots['a'])
        self.assertEqual(state['teacher_history'],[{'edit':'a'}])
        self.assertEqual(state['format_report'],'format-a')
        snapshots = sync_batch(state, ['a','b'], 'a', 'changed-course')
        activate_paper(state, snapshots['a'])
        self.assertNotIn('analysis_run',state)
        self.assertTrue(all('analysis_run' not in snapshot for snapshot in snapshots.values()))
        self.assertEqual(state['format_report'],'format-a')

    def test_processing_continues_after_failure_and_skips_existing_results(self):
        papers = collect_uploads([upload('a.pdf'),upload('b.pdf'),upload('c.pdf')])
        snapshots = {item.key:{'parsed_document':replace(demo_document(),filename=item.name),'parse_signature':item.key} for item in papers}
        completed = analyze_document(demo_document(),self.rubric,self.settings)
        snapshots[papers[2].key]['analysis_run'] = completed
        visited = []
        def analyzer(document, *args, **kwargs):
            visited.append(document.filename)
            if document.filename == 'a.pdf':
                raise AssistantError('受控失败')
            return completed
        analyze_batch(papers,snapshots,self.rubric,self.settings,'',allow_cloud=False,analyzer=analyzer)
        self.assertEqual(visited,['a.pdf','b.pdf'])
        self.assertEqual(snapshots[papers[0].key]['analysis_error'],'受控失败')
        self.assertIs(snapshots[papers[1].key]['analysis_run'],completed)
        self.assertIs(snapshots[papers[2].key]['analysis_run'],completed)

    def test_real_batch_requires_consent_before_any_analyzer_call(self):
        with patch('paper_assistant.analysis_service.analyze_document') as analyzer:
            with self.assertRaisesRegex(AssistantError,'确认'):
                analyze_batch([],{},self.rubric,Settings(mode='real'),'',allow_cloud=False,analyzer=analyzer)
            analyzer.assert_not_called()

    def test_zip_preserves_reports_and_errors_without_paths_or_duplicate_overwrites(self):
        papers = collect_uploads([upload('../../same.pdf'),upload('..\\same.pdf'),upload('failed.pdf')])
        run = analyze_document(demo_document(),self.rubric,self.settings)
        snapshots = {papers[0].key:{'analysis_run':run},papers[1].key:{'analysis_run':run},
                     papers[2].key:{'parse_error':'无效PDF'}}
        with zipfile.ZipFile(BytesIO(export_batch(papers,snapshots))) as archive:
            names = archive.namelist()
            self.assertEqual(len(names),len(set(names)))
            self.assertTrue(all('/' not in name and '\\' not in name for name in names))
            self.assertEqual(sum(name.endswith('.md') for name in names),2)
            manifest = json.loads(archive.read('批次清单.json'))
            self.assertEqual(manifest[-1]['原因'],'无效PDF')
            report = json.loads(archive.read(manifest[0]['报告'][1]))
            self.assertFalse(report['teacher_review']['confirmed'])


class BatchInterfaceTests(unittest.TestCase):
    setUp = configuration.ConfigurationTests.setUp
    app = configuration.ConfigurationTests.app
    save_form = configuration.ConfigurationTests.save_form

    def test_advanced_controls_hidden_and_invalid_numeric_uses_preset(self):
        self.path.write_text('MODEL_TIMEOUT_SECONDS=invalid\n',encoding='utf-8')
        app = self.app(SETTINGS_PAGE)
        self.assertEqual(len(app.number_input),0)
        self.assertFalse(any('兼容选项' in item.label for item in app.expander))
        app.text_input(key='config_base_url').set_value(self.settings.model_base_url)
        app.text_input(key='config_api_key').set_value(self.settings.model_api_key)
        app.text_input(key='config_model_name').set_value(self.settings.model_name)
        self.save_form(app)
        from paper_assistant.config import load_settings
        self.assertEqual(load_settings(mode='real').model_timeout_seconds,45)

    def test_batch_overlimit_blocks_without_parsing(self):
        app = self.app(PRODUCTION_PAGE)
        files = [(f'{index}.pdf',make_pdf(),'application/pdf') for index in range(11)]
        with patch('paper_assistant.ui.parse_document') as parser:
            app.file_uploader[0].set_value(files).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('最多 10' in item.value for item in app.error))
        self.assertTrue(app.button(key='start_analysis').disabled)
        parser.assert_not_called()

    def test_real_multi_upload_consent_results_switching_review_and_zip(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json=envelope(valid_response(request)))
        environment = {'MODEL_API_KEY':'controlled-only-key','MODEL_NAME':'controlled-model',
                       'MODEL_BASE_URL':'https://controlled.invalid/v1'}
        with patch.dict('os.environ',environment), patch('paper_assistant.model_client.HTTPChatTransport',
                side_effect=lambda settings: HTTPChatTransport(settings,transport=httpx.MockTransport(handler))):
            app = self.app(PRODUCTION_PAGE)
            files = [('bad.pdf',b'invalid','application/pdf'),('A.pdf',make_pdf(),'application/pdf'),('B.pdf',make_pdf(),'application/pdf')]
            app.file_uploader[0].set_value(files).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key='start_batch').disabled)
            self.assertFalse(calls)
            next(item for item in app.checkbox if item.key.startswith('cloud_ack_')).check().run()
            app.button(key='start_batch').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(calls),14)
            self.assertEqual(app.session_state['analysis_run'].document.filename,'A.pdf')
            self.assertFalse(app.session_state['analysis_run'].result.data['is_mock'])
            self.assertTrue(app.download_button(key='download_batch_reports'))
            app.toggle(key='evaluation_review_enabled').set_value(True).run()
            token = app.session_state['analysis_run_token']
            prefix = f'grade_review_{token}_question'
            app.number_input(key=prefix+'_score').set_value(10.0)
            app.text_area(key=prefix+'_rationale').set_value('受控复核依据')
            app.button(key=prefix+'_save').click().run()
            self.assertEqual(len(app.session_state['teacher_history']),1)
            keys = list(app.session_state['batch_papers'])
            app.selectbox(key='batch_selected').select(keys[2]).run()
            self.assertEqual(app.session_state['analysis_run'].document.filename,'B.pdf')
            self.assertEqual(len(app.session_state.get('teacher_history',[])),0)
            app.selectbox(key='batch_selected').select(keys[1]).run()
            self.assertEqual(len(app.session_state['teacher_history']),1)
            app.text_area(key='course_requirements').set_value('更换课程要求').run()
            self.assertNotIn('analysis_run',app.session_state)
            self.assertTrue(all('analysis_run' not in item for item in app.session_state['batch_papers'].values()))
            self.assertFalse(next(item for item in app.checkbox if item.key.startswith('cloud_ack_')).value)
            self.assertEqual(len(calls),14)

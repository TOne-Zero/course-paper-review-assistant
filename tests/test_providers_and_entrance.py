"""服务切换、密钥隔离和正式入口边界回归，不访问外部服务。"""

import unittest

from streamlit.testing.v1 import AppTest

from paper_assistant.config import PROJECT_ROOT, load_settings
from paper_assistant.model_configuration import save_model_settings
from paper_assistant.providers import BY_NAME, provider_for_url, resolve_api_key
from paper_assistant.routes import PRODUCTION_PAGE, SETTINGS_PAGE
from paper_assistant.schemas import AssistantError
from tests import test_configuration as configuration


class ProviderAndEntranceTests(unittest.TestCase):
    # 仅复用临时.env隔离与表单助手，不重复继承原测试集。
    setUp = configuration.ConfigurationTests.setUp
    app = configuration.ConfigurationTests.app
    save_form = configuration.ConfigurationTests.save_form
    def test_landing_native_button_enters_production(self):
        app = AppTest.from_file(str(PROJECT_ROOT / 'app.py'), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key='enter_workspace'))
        app.button(key='enter_workspace').click().run()
        self.assertTrue(app.button(key='open_api_configuration'))
        self.assertTrue(app.button(key='open_header_settings'))
        self.assertTrue(app.button(key='start_analysis').disabled)
        self.assertFalse(app.exception)

    def test_formal_has_no_mock_controls_or_links_and_header_opens_setup(self):
        app = self.app(PRODUCTION_PAGE)
        self.assertFalse(any(item.key == 'use_demo' for item in app.checkbox))
        self.assertFalse(any(item.key == 'download_demo_paper' for item in app.get('download_button')))
        self.assertFalse(any('模拟' in str(item.value) for item in [*app.caption, *app.markdown]))
        self.assertFalse(any(item.proto.label == '模拟运行' for item in app.get('page_link')))
        app.button(key='open_header_settings').click().run()
        self.assertTrue(app.selectbox(key='config_provider'))
        self.assertFalse(app.exception)

    def test_provider_selection_fills_url_and_clears_draft_credentials(self):
        app = self.app(SETTINGS_PAGE)
        app.text_input(key='config_api_key').set_value('draft-only-key')
        app.text_input(key='config_model_name').set_value('draft-model')
        app.selectbox(key='config_provider').select('DeepSeek').run()
        self.assertEqual(app.text_input(key='config_base_url').value, BY_NAME['DeepSeek'].base_url)
        self.assertEqual(app.text_input(key='config_api_key').value, '')
        self.assertEqual(app.text_input(key='config_model_name').value, '')
        app.selectbox(key='config_provider').select('自定义').run()
        self.assertEqual(app.text_input(key='config_base_url').value, '')
        self.assertFalse(self.path.exists())

    def test_switching_endpoint_cannot_reuse_saved_secret(self):
        save_model_settings(self.settings)
        original = self.path.read_bytes()
        app = self.app(SETTINGS_PAGE)
        app.selectbox(key='config_provider').select('DeepSeek').run()
        app.text_input(key='config_model_name').set_value('test-model')
        self.save_form(app)
        self.assertTrue(any('重新填写' in item.value for item in app.error))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertNotIn(self.settings.model_api_key, str([item.value for item in app.error]))
        app.text_input(key='config_api_key').set_value('new-service-test-only-key')
        self.save_form(app)
        self.assertFalse(app.exception)
        self.assertEqual(load_settings(mode='real').model_api_key, 'new-service-test-only-key')
        self.assertEqual(load_settings(mode='real').model_base_url, BY_NAME['DeepSeek'].base_url)

    def test_manual_address_change_also_requires_new_key(self):
        values = {'MODEL_BASE_URL':self.settings.model_base_url, 'MODEL_API_KEY':self.settings.model_api_key}
        self.assertEqual(resolve_api_key(self.settings.model_base_url + '/', '', values), self.settings.model_api_key)
        with self.assertRaises(AssistantError):
            resolve_api_key('https://another.invalid/v1', '', values)
        self.assertEqual(provider_for_url(' https://api.deepseek.com/ '), 'DeepSeek')

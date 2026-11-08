"""模型配置保存、密钥处理和固定模式路由的回归测试，不连接外部服务。"""

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

from paper_assistant.config import PROJECT_ROOT, Settings, load_settings
from paper_assistant.model_configuration import save_model_settings
from paper_assistant.routes import DEMO_PAGE, PRODUCTION_PAGE, SETTINGS_PAGE
from paper_assistant.schemas import AssistantError


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / ".env"
        local = patch("paper_assistant.config.LOCAL_ENV_PATH", self.path)
        local.start()
        self.addCleanup(local.stop)
        environment = patch.dict("os.environ", {})
        environment.start()
        self.addCleanup(environment.stop)
        for name in list(os.environ):
            if name.startswith("MODEL_") or name == "ANALYSIS_MODE":
                os.environ.pop(name)
        self.settings = Settings(mode="real", model_api_key="test-only-not-a-real-secret", model_name="test-model",
                                 model_base_url="https://controlled.invalid/v1")

    def app(self, page=None):
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
        return app.switch_page(page or PRODUCTION_PAGE).run()

    def save_form(self, app):
        next(button for button in app.button if button.label == "保存配置").click().run()

    def test_roundtrip_is_immediate_without_process_environment_mutation(self):
        save_model_settings(self.settings)
        loaded = load_settings(mode="real")
        self.assertEqual(loaded.model_api_key, self.settings.model_api_key)
        self.assertEqual(loaded.model_base_url, self.settings.model_base_url)
        self.assertNotIn("MODEL_API_KEY", os.environ)
        self.assertNotIn(self.settings.model_api_key, repr(loaded))
        save_model_settings(replace(self.settings, model_name="updated-model"))
        self.assertEqual(load_settings(mode="real").model_name, "updated-model")

    def test_saving_preserves_unrelated_and_multiline_settings(self):
        self.path.write_text('# keep this comment\nMAX_PDF_MB=8\nCUSTOM_NOTE="first\nMODEL_NAME=inside-a-note\nlast"\n', encoding="utf-8")
        key = "test-only-key-with'quote"
        save_model_settings(replace(self.settings, model_api_key=key))
        values = dotenv_values(self.path, interpolate=False)
        self.assertEqual(values["MAX_PDF_MB"], "8")
        self.assertEqual(values["CUSTOM_NOTE"], "first\nMODEL_NAME=inside-a-note\nlast")
        self.assertEqual(values["MODEL_API_KEY"], key)
        self.assertIn("# keep this comment", self.path.read_text(encoding="utf-8"))

    def test_invalid_settings_never_replace_existing_file(self):
        self.path.write_text("UNRELATED=keep\n", encoding="utf-8")
        for settings in [replace(self.settings, model_base_url="http://remote.invalid/v1"),
                         replace(self.settings, model_base_url="https://controlled.invalid/v1?key=secret"),
                         replace(self.settings, model_name="bad\nname"),
                         replace(self.settings, model_chunk_characters=12001, model_batch_characters=12000),
                         replace(self.settings, model_api_key="bad\r\nkey")]:
            with self.subTest(settings=settings), self.assertRaises(AssistantError):
                save_model_settings(settings)
            self.assertEqual(self.path.read_text(encoding="utf-8"), "UNRELATED=keep\n")

    def test_write_failure_leaves_original_and_sanitizes_error(self):
        self.path.write_text("UNRELATED=keep\n", encoding="utf-8")
        with patch("paper_assistant.model_configuration.os.replace", side_effect=OSError(self.settings.model_api_key)):
            with self.assertRaises(AssistantError) as error:
                save_model_settings(self.settings)
        self.assertNotIn(self.settings.model_api_key, str(error.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "UNRELATED=keep\n")
        self.assertFalse(list(self.path.parent.glob(".env.*.tmp")))

    def test_environment_override_is_reported_without_writing_or_echoing_secret(self):
        with patch.dict("os.environ", {"MODEL_API_KEY":"environment-test-secret"}):
            with self.assertRaises(AssistantError) as error:
                save_model_settings(self.settings)
        self.assertIn("MODEL_API_KEY", str(error.exception))
        self.assertNotIn("environment-test-secret", str(error.exception))
        self.assertFalse(self.path.exists())

    def test_simulation_does_not_depend_on_invalid_real_service_settings(self):
        self.path.write_text("ANALYSIS_MODE=real\nMODEL_TIMEOUT_SECONDS=invalid\n", encoding="utf-8")
        settings = load_settings(mode="mock")
        self.assertEqual(settings.mode, "mock")
        self.assertEqual(settings.model_api_key, "")
        with self.assertRaises(AssistantError):
            load_settings(mode="real")

    def test_production_is_fixed_real_and_configuration_notice_opens_setup(self):
        with patch.dict("os.environ", {"ANALYSIS_MODE":"mock"}):
            app = self.app()
            app.query_params["mode"] = "mock"
            app.run()
            self.assertTrue(app.button(key="start_analysis").disabled)
            self.assertEqual(len(app.radio), 0)
            app.button(key="open_api_configuration").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.text_input(key="config_base_url"))
            self.assertTrue(any("配置要求" in item.value for item in app.subheader))

    def test_demo_is_fixed_mock_even_when_query_and_environment_request_real(self):
        with patch.dict("os.environ", {"ANALYSIS_MODE":"real", "MODEL_TIMEOUT_SECONDS":"invalid"}), patch(
                "paper_assistant.model_client.HTTPChatTransport") as transport:
            app = self.app(DEMO_PAGE)
            app.query_params["mode"] = "real"
            app.run()
            app.checkbox(key="use_demo").check().run()
            app.button(key="start_analysis").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["analysis_run"].result.data["is_mock"])
            transport.assert_not_called()

    def test_switching_to_formal_clears_simulated_scores_and_blocks_analysis(self):
        app = self.app(DEMO_PAGE)
        app.checkbox(key="use_demo").check().run()
        app.button(key="start_analysis").click().run()
        self.assertIn("analysis_run", app.session_state)
        app.switch_page(PRODUCTION_PAGE).run()
        self.assertNotIn("analysis_run", app.session_state)
        self.assertTrue(app.button(key="start_analysis").disabled)

    def test_setup_saves_without_network_and_clears_secret_field(self):
        app = self.app(SETTINGS_PAGE)
        app.text_input(key="config_base_url").set_value(self.settings.model_base_url)
        app.text_input(key="config_model_name").set_value(self.settings.model_name)
        app.text_input(key="config_api_key").set_value(self.settings.model_api_key)
        with patch("paper_assistant.model_client.HTTPChatTransport") as transport:
            self.save_form(app)
        self.assertFalse(app.exception)
        transport.assert_not_called()
        self.assertEqual(load_settings(mode="real").model_api_key, self.settings.model_api_key)
        self.assertEqual(app.text_input(key="config_api_key").value, "")
        self.assertFalse(any(self.settings.model_api_key in str(item.value) for item in [*app.caption, *app.markdown, *app.success]))
        app.switch_page(PRODUCTION_PAGE).run()
        self.assertFalse(any(button.key == "open_api_configuration" for button in app.button))
        self.assertFalse(app.exception)

    def test_blank_key_preserves_existing_secret_and_other_configuration(self):
        save_model_settings(self.settings)
        with self.path.open("a", encoding="utf-8") as output:
            output.write("MAX_PDF_MB=9\n")
        app = self.app(SETTINGS_PAGE)
        self.assertEqual(app.text_input(key="config_api_key").value, "")
        app.text_input(key="config_model_name").set_value("replacement-model")
        self.save_form(app)
        self.assertFalse(app.exception)
        loaded = load_settings(mode="real")
        self.assertEqual(loaded.model_api_key, self.settings.model_api_key)
        self.assertEqual(loaded.model_name, "replacement-model")
        self.assertEqual(loaded.max_pdf_mb, 9)

    def test_invalid_numeric_configuration_is_repairable_from_setup(self):
        self.path.write_text("MODEL_TIMEOUT_SECONDS=invalid\n", encoding="utf-8")
        app = self.app()
        app.button(key="open_api_configuration").click().run()
        # AppTest 的 switch_page 哈希需显式跟随按钮导航，真实浏览器按 URL 跟随。
        app.switch_page(SETTINGS_PAGE).run()
        app.text_input(key="config_base_url").set_value(self.settings.model_base_url)
        app.text_input(key="config_model_name").set_value(self.settings.model_name)
        app.text_input(key="config_api_key").set_value(self.settings.model_api_key)
        self.save_form(app)
        self.assertFalse(app.exception)
        self.assertEqual(load_settings(mode="real").model_timeout_seconds, 45)

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest

from paper_assistant.api_transport import HTTPChatTransport
from paper_assistant.config import PROJECT_ROOT
from paper_assistant.routes import DEMO_PAGE, PRODUCTION_PAGE
from paper_assistant.report_exporter import export_json, export_markdown
from tests.api_responses import envelope, valid_response


class EvaluationInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"ANALYSIS_MODE": "mock", "MODEL_API_KEY": "", "MODEL_NAME": "", "MODEL_BASE_URL": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
        self.app.switch_page(DEMO_PAGE).run()

    def upload_demo(self):
        source = PROJECT_ROOT / "examples" / "演示论文_原创虚构.pdf"
        self.app.file_uploader[0].set_value((source.name, source.read_bytes(), "application/pdf")).run()

    def test_mock_upload_review_confirm_and_both_export_formats(self):
        self.upload_demo()
        self.app.button(key="start_analysis").click().run()
        self.assertEqual(len(self.app.exception), 0)
        before = self.app.session_state["analysis_run"].result.data["dimensions"][0]["score"]
        self.app.toggle(key="evaluation_review_enabled").set_value(True).run()
        token = self.app.session_state["analysis_run_token"]
        prefix = f"grade_review_{token}_question"
        self.app.number_input(key=prefix + "_score").set_value(10.0).run()
        self.app.text_area(key=prefix + "_opinion").set_value("演示教师意见：问题范围还可缩小。").run()
        self.app.text_area(key=prefix + "_rationale").set_value("已对照原文研究问题段核对。").run()
        self.app.button(key=prefix + "_save").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state["analysis_run"].result.data["dimensions"][0]["score"], before)
        self.app.checkbox(key=f"confirm_all_{token}").check().run()
        self.app.button(key="confirm_evaluation_review").click().run()
        run = self.app.session_state["analysis_run"]
        history = self.app.session_state["teacher_history"]
        confirmation = self.app.session_state["teacher_confirmation"]
        data = json.loads(export_json(run.result, history, confirmation))
        self.assertTrue(data["teacher_review"]["confirmed"])
        self.assertEqual(data["teacher_review"]["dimensions"][0]["score"], 10)
        self.assertIn("演示教师意见", export_markdown(run.result, history, confirmation).decode("utf-8"))
        self.assertTrue(self.app.download_button(key="download_evaluation_json"))

    def test_real_mode_does_not_call_without_consent_then_handles_missing_score(self):
        sent = []
        def handler(request):
            sent.append(request)
            result = valid_response(request)
            if result["dimension_id"] == "question":
                result.update(status="unscorable", score=None, evidence=[], reason="受控测试：此维度材料不足。")
            return httpx.Response(200, json=envelope(result))
        with patch.dict("os.environ", {"MODEL_API_KEY": "controlled-test-key", "MODEL_NAME": "controlled-model", "MODEL_BASE_URL": "https://controlled.invalid/v1"}), patch(
            "paper_assistant.model_client.HTTPChatTransport", side_effect=lambda settings: HTTPChatTransport(settings, transport=httpx.MockTransport(handler))):
            self.app.switch_page(PRODUCTION_PAGE).run()
            self.upload_demo()
            self.assertTrue(self.app.button(key="start_analysis").disabled)
            self.assertFalse(sent)
            ack = next(item for item in self.app.checkbox if item.key.startswith("cloud_ack_"))
            ack.check().run()
            self.app.button(key="start_analysis").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertTrue(sent)
            self.assertIsNone(self.app.session_state["analysis_run"].result.data["total_score"])
            self.assertIn("总分待教师确认", self.app.metric[0].value)
            self.app.toggle(key="evaluation_review_enabled").set_value(True).run()
            token = self.app.session_state["analysis_run_token"]
            self.assertIsNone(self.app.number_input(key=f"grade_review_{token}_question_score").value)

    def test_missing_api_configuration_is_clear_and_blocks_calling(self):
        self.app.switch_page(PRODUCTION_PAGE).run()
        self.upload_demo()
        self.assertTrue(self.app.button(key="start_analysis").disabled)
        self.assertTrue(self.app.button(key="open_api_configuration"))
        self.assertIn("点击配置", self.app.button(key="open_api_configuration").label)

    def test_cleanup_resets_upload_analysis_review_and_consent(self):
        self.upload_demo()
        self.app.button(key="start_analysis").click().run()
        with patch("paper_assistant.ui.clear_managed_files", return_value={"deleted_files": 0, "not_removed": 0}) as cleanup:
            self.app.button(key="clear_private_data").click().run()
            cleanup.assert_called_once()
        self.assertEqual(len(self.app.exception), 0)
        self.assertIsNone(self.app.file_uploader[0].value)
        self.assertNotIn("analysis_run", self.app.session_state)
        self.assertNotIn("teacher_history", self.app.session_state)
        self.assertTrue(self.app.button(key="start_analysis").disabled)

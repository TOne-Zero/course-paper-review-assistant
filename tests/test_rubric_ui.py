import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from paper_assistant.rubrics import export_rubric, load_rubrics, rubric_to_dict
from paper_assistant.routes import DEMO_PAGE


APP = Path(__file__).resolve().parents[1] / "app.py"


class RubricInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.local_patch = patch("paper_assistant.rubrics.LOCAL_DIRECTORY", self.directory)
        self.local_patch.start()
        self.addCleanup(self.local_patch.stop)
        self.environment = patch.dict("os.environ", {"ANALYSIS_MODE": "mock"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = AppTest.from_file(str(APP), default_timeout=20).run()
        self.app.switch_page(DEMO_PAGE).run()
        self.app.toggle(key="teacher_demo").set_value(True).run()

    def test_teacher_mode_notice_and_save_reload(self):
        self.assertTrue(any("不代表身份认证" in item.value for item in self.app.warning))
        self.app.button(key="save_rubric").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(list(self.directory.glob("*.json"))), 1)
        selected_id = self.app.selectbox(key="course_rubric").value
        self.assertTrue(selected_id.startswith("local_"))
        self.assertEqual(load_rubrics(self.directory)[0].version, "local-1")
        self.app.button(key="save_rubric").click().run()
        self.assertEqual(load_rubrics(self.directory)[0].version, "local-2")

    def test_invalid_total_disables_save_without_writing(self):
        self.app.number_input[0].set_value(16.0).run()
        self.assertTrue(self.app.button(key="save_rubric").disabled)
        self.assertTrue(any("满分合计必须为 100" in item.value for item in self.app.error))
        self.assertFalse(list(self.directory.glob("*.json")))

    def test_adjusted_dimension_and_scores_are_saved_and_exported(self):
        token = self.app.session_state["rubric_draft_token"]
        self.app.text_input(key=f"rubric_{token}_question_name").set_value("研究问题（课程调整）").run()
        self.app.number_input(key=f"rubric_{token}_question_score").set_value(16.0).run()
        self.app.number_input(key=f"rubric_{token}_literature_score").set_value(14.0).run()
        self.app.text_area(key=f"rubric_{token}_question_checks").set_value("检查问题是否具体\n检查范围是否适当").run()
        self.app.button(key="save_rubric").click().run()
        self.assertEqual(len(self.app.exception), 0)
        saved = load_rubrics(self.directory)[0]
        self.assertEqual(saved.dimensions[0].name, "研究问题（课程调整）")
        self.assertEqual([item.max_score for item in saved.dimensions[:2]], [16, 14])
        self.assertEqual(saved.dimensions[0].checklist, ("检查问题是否具体", "检查范围是否适当"))
        self.assertEqual(saved.total_score, 100)
        self.assertEqual(len(saved.references), 4)
        from paper_assistant.rubrics import import_rubric
        self.assertEqual(import_rubric(export_rubric(saved)), saved)

    def test_add_and_remove_dimension_keeps_total_and_saves(self):
        token = self.app.session_state["rubric_draft_token"]
        self.app.checkbox(key=f"rubric_{token}_format_remove").check().run()
        self.app.button(key="add_rubric_dimension").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertFalse(self.app.button(key="save_rubric").disabled)
        self.app.button(key="save_rubric").click().run()
        self.assertEqual(len(self.app.exception), 0)
        saved = load_rubrics(self.directory)[0]
        self.assertEqual(len(saved.dimensions), 7)
        self.assertNotIn("format", {item.id for item in saved.dimensions})
        self.assertIn("新增维度", {item.name for item in saved.dimensions})
        self.assertEqual(saved.total_score, 100)

    def test_import_roundtrip_and_invalid_import(self):
        source = next(item for item in load_rubrics() if item.id == "course_demo")
        self.app.file_uploader(key="import_rubric").set_value(("课程标准.json", export_rubric(source), "application/json")).run()
        self.app.button(key="apply_import_rubric").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(list(self.directory.glob("*.json"))), 1)
        self.assertEqual(load_rubrics(self.directory)[0].dimensions, source.dimensions)
        invalid = rubric_to_dict(source)
        invalid["dimensions"][0]["max_score"] = -1
        self.app.file_uploader(key="import_rubric").set_value(("错误.json", json.dumps(invalid).encode(), "application/json")).run()
        self.app.button(key="apply_import_rubric").click().run()
        self.assertEqual(len(list(self.directory.glob("*.json"))), 1)
        self.assertTrue(any("评分标准无效" in item.value for item in self.app.error))

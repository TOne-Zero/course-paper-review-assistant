import copy
import json
import unittest

from paper_assistant.analysis_service import analyze_document
from paper_assistant.config import Settings
from paper_assistant.demo import demo_document
from paper_assistant.evaluation_contract import unscored
from paper_assistant.model_client import MockModelClient
from paper_assistant.report_exporter import export_json, export_markdown
from paper_assistant.rubrics import load_rubrics
from paper_assistant.schemas import AssistantError, ValidatedResult
from paper_assistant.teacher_review import add_teacher_edit, confirm_review, review_summary
from paper_assistant.validator import validate_result


class ReviewReportTests(unittest.TestCase):
    def setUp(self):
        self.document, self.rubric = demo_document(), load_rubrics()[0]
        self.result = analyze_document(self.document, self.rubric, Settings()).result

    def missing_result(self):
        raw = MockModelClient().evaluate(self.document, self.rubric)
        raw["dimensions"][0] = unscored(self.rubric.dimensions[0], "本维度缺少材料，无法评分。")
        raw["total_score"] = None
        return validate_result(raw, self.document, self.rubric)

    def test_total_is_program_sum_and_missing_not_zero(self):
        self.assertEqual(self.result.data["total_score"], round(sum(item["score"] for item in self.result.data["dimensions"]), 2))
        result = self.missing_result()
        self.assertIsNone(review_summary(result, [])["total_score"])
        self.assertEqual(review_summary(result, [])["total_label"], "总分待教师确认")
        with self.assertRaisesRegex(AssistantError, "未评分"):
            confirm_review(result, [])
        report = export_markdown(result).decode("utf-8")
        self.assertIn("总分待教师确认", report)
        self.assertIsNone(json.loads(export_json(result))["dimensions"][0]["score"])

    def test_edit_history_keeps_ai_and_previous_teacher_values(self):
        before = copy.deepcopy(self.result.data)
        dimension = self.rubric.dimensions[0]
        history = add_teacher_edit(self.result, [], dimension.id, 10, "第一次意见", "核对原文后调整。")
        history = add_teacher_edit(self.result, history, dimension.id, 11, "第二次意见", "补充核对材料。")
        self.assertEqual(history[1]["previous_score"], 10)
        self.assertEqual(history[1]["previous_opinion"], "第一次意见")
        self.assertEqual(self.result.data, before)
        self.assertEqual(review_summary(self.result, history)["dimensions"][0]["score"], 11)

    def test_teacher_can_complete_unscored_or_intentionally_enter_zero(self):
        result = self.missing_result()
        history = add_teacher_edit(result, [], self.rubric.dimensions[0].id, 0, "本地人工意见", "教师主动填入零分，不是程序补零。")
        self.assertIsNotNone(review_summary(result, history)["total_score"])
        self.assertIsNone(result.data["dimensions"][0]["score"])
        self.assertEqual(review_summary(result, history)["dimensions"][0]["score"], 0)

    def test_invalid_teacher_score_and_missing_rationale_are_rejected(self):
        for value in (-1, 999, True, float("nan"), 1.001):
            with self.subTest(value=value), self.assertRaises(AssistantError):
                add_teacher_edit(self.result, [], self.rubric.dimensions[0].id, value, "意见", "依据")
        with self.assertRaises(AssistantError):
            add_teacher_edit(self.result, [], self.rubric.dimensions[0].id, 10, "意见", "")

    def test_confirmation_is_bound_to_evaluation_and_invalidated_by_edit(self):
        confirmation = confirm_review(self.result, [])
        self.assertTrue(review_summary(self.result, [], confirmation)["confirmed"])
        history = add_teacher_edit(self.result, [], self.rubric.dimensions[0].id, 10, "意见", "依据")
        self.assertFalse(review_summary(self.result, history, confirmation)["confirmed"])
        another = analyze_document(self.document, self.rubric, Settings()).result
        self.assertFalse(review_summary(another, [], confirmation)["confirmed"])
        with self.assertRaises(AssistantError):
            review_summary(another, history)

    def test_both_exports_include_versions_model_history_and_unverified_opinion_notice(self):
        history = add_teacher_edit(self.result, [], self.rubric.dimensions[0].id, 10, "人工补充判断", "人工核对依据")
        confirmation = confirm_review(self.result, history)
        data = json.loads(export_json(self.result, history, confirmation))
        self.assertEqual(data["rubric"]["version"], self.rubric.version)
        self.assertEqual(data["model"]["name"], "mock-local-v2")
        self.assertTrue(data["teacher_review"]["confirmed"])
        self.assertEqual(len(data["teacher_review"]["history"]), 1)
        text = export_markdown(self.result, history, confirmation).decode("utf-8")
        for expected in ("AI辅助评价，最终成绩由教师确定", "mock", "评价时间", "人工复核状态", "未由程序核实", "文档解析", "人工补充判断"):
            self.assertIn(expected, text)

    def test_unverified_quote_is_never_exported(self):
        data = copy.deepcopy(self.result.data)
        data["dimensions"][0]["evidence"][0]["verified"] = False
        for function in (export_json, export_markdown):
            with self.subTest(function=function.__name__), self.assertRaises(AssistantError):
                function(ValidatedResult(data))

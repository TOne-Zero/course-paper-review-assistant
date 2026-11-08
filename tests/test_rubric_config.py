import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_assistant.rubrics import export_rubric, import_rubric, load_rubrics, parse_rubric_config, rubric_to_dict, save_rubric
from paper_assistant.schemas import AssistantError


class RubricConfigTests(unittest.TestCase):
    def setUp(self):
        self.rubric = next(item for item in load_rubrics() if item.id == "course_demo")

    def test_seven_dimension_demo_is_explicit_and_totals_100(self):
        self.assertEqual([item.name for item in self.rubric.dimensions], ["研究问题", "文献与理论", "方法", "分析", "结论", "写作", "格式"])
        self.assertEqual(self.rubric.total_score, 100)
        self.assertTrue(self.rubric.is_demo)
        self.assertIn("演示标准", self.rubric.name)
        self.assertIn("不是中国传媒大学", self.rubric.description)
        self.assertTrue(all(item.checklist and item.score_bands for item in self.rubric.dimensions))

    def test_export_import_roundtrip_preserves_whole_contract(self):
        self.assertEqual(import_rubric(export_rubric(self.rubric)), self.rubric)

    def test_references_and_weight_notice_survive_local_save(self):
        self.assertIn("不是文献原始量表", self.rubric.weight_note)
        self.assertEqual({source.id for source in self.rubric.references}, {"R05", "R06", "R07", "R09"})
        with tempfile.TemporaryDirectory() as name:
            saved = save_rubric(replace(self.rubric, id="local_cited"), Path(name))
            restored = import_rubric(export_rubric(load_rubrics(Path(name))[0]))
            self.assertEqual(restored.references, saved.references)
            self.assertEqual(restored.weight_note, saved.weight_note)
            self.assertEqual(restored.dimensions[0].reference_ids, saved.dimensions[0].reference_ids)

    def test_old_v2_without_reference_fields_remains_importable(self):
        data = rubric_to_dict(self.rubric)
        data.pop("references")
        data.pop("weight_note")
        for dimension in data["dimensions"]:
            dimension.pop("reference_ids")
        loaded = import_rubric(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(loaded.references, ())
        self.assertEqual(loaded.total_score, 100)

    def test_invalid_reference_links_and_unknown_ids_are_rejected(self):
        for url in ("javascript:alert(1)", "file:///secret", "https://user:password@example.com", "http://[bad"):
            data = rubric_to_dict(self.rubric)
            data["references"][0]["url"] = url
            with self.subTest(url=url), self.assertRaises(AssistantError):
                parse_rubric_config(data)
        data = rubric_to_dict(self.rubric)
        data["dimensions"][0]["reference_ids"] = ["R_UNKNOWN"]
        with self.assertRaises(AssistantError):
            parse_rubric_config(data)

    def test_save_read_update_and_version_are_consistent(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            saved = save_rubric(replace(self.rubric, id="local_test"), directory)
            self.assertEqual(saved.version, "local-1")
            self.assertEqual(load_rubrics(directory), (saved,))
            updated = save_rubric(replace(saved, name="调整后的本地标准"), directory, expected_version="local-1")
            self.assertEqual(updated.version, "local-2")
            self.assertEqual(load_rubrics(directory), (updated,))
            self.assertEqual(len(list(directory.iterdir())), 1)
            with self.assertRaisesRegex(AssistantError, "其它页面更新"):
                save_rubric(saved, directory, expected_version="local-1")
            self.assertEqual(load_rubrics(directory), (updated,))

    def test_illegal_values_never_create_configuration_file(self):
        for value in (-1, 0, True, float("nan"), float("inf"), 100.001, "15", None):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as name:
                broken = replace(self.rubric, id="local_invalid", dimensions=(
                    replace(self.rubric.dimensions[0], max_score=value), *self.rubric.dimensions[1:],
                ))
                with self.assertRaises((AssistantError, ValueError)):
                    save_rubric(broken, Path(name))
                self.assertFalse(list(Path(name).glob("*.json")))

    def test_invalid_totals_and_band_gaps_are_rejected(self):
        original = rubric_to_dict(self.rubric)
        cases = []
        altered = copy.deepcopy(original)
        altered["dimensions"][0]["max_score"] = 16
        cases.append(altered)
        altered = copy.deepcopy(original)
        altered["total_score"] = 99
        cases.append(altered)
        altered = copy.deepcopy(original)
        altered["dimensions"][0]["score_bands"][1]["min_ratio"] = 0.65
        cases.append(altered)
        altered = copy.deepcopy(original)
        altered["dimensions"][0]["checklist"] = []
        cases.append(altered)
        altered = copy.deepcopy(original)
        altered["dimensions"][1]["id"] = altered["dimensions"][0]["id"]
        cases.append(altered)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(AssistantError):
                parse_rubric_config(data)

    def test_fractional_scores_do_not_fail_from_float_accumulation(self):
        data = rubric_to_dict(self.rubric)
        data["dimensions"][0]["max_score"] = 14.1
        data["dimensions"][1]["max_score"] = 15.9
        rubric = parse_rubric_config(data)
        self.assertEqual(import_rubric(export_rubric(rubric)).total_score, 100)

    def test_unsafe_identifier_or_builtin_overwrite_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            for rubric_id in ("../../escape", "local_../escape", "course_demo"):
                with self.subTest(rubric_id=rubric_id), self.assertRaises(AssistantError):
                    save_rubric(replace(self.rubric, id=rubric_id), Path(name))

    def test_invalid_imports_are_actionable(self):
        for content in (b"", b"not json", b"\xff\xfe", b'{"schema_version":"2.0","id":"a","id":"b"}', b"x" * (1024 * 1024 + 1)):
            with self.subTest(size=len(content)), self.assertRaises(AssistantError):
                import_rubric(content)


if __name__ == "__main__":
    unittest.main()

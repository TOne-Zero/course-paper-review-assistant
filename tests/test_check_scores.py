import copy
import unittest

from paper_assistant.config import Settings
from paper_assistant.model_client import MockModelClient
from paper_assistant.paper_context import plan_evaluation
from paper_assistant.pdf_parser import parse_pdf
from paper_assistant.rubric_defaults import weighted_rubric
from paper_assistant.rubrics import load_rubrics
from paper_assistant.schemas import AssistantError
from paper_assistant.validator import validate_dimension, validate_result
from tests.pdf_fixture import make_pdf


class CheckScoreTests(unittest.TestCase):
    def setUp(self):
        self.rubric = weighted_rubric(load_rubrics()[0])
        self.document = parse_pdf(make_pdf(), 'controlled.pdf', Settings())
        self.payload = MockModelClient().evaluate(self.document, self.rubric)
        self.chunks = plan_evaluation(self.document, self.rubric, Settings()).chunks
        self.dimension = self.rubric.dimensions[0]
        item = self.payload['dimensions'][0]
        self.raw = {key: copy.deepcopy(item[key]) for key in ('dimension_id', 'status', 'score', 'max_score', 'reason', 'evidence', 'suggestions', 'needs_teacher_review', 'check_scores')}
        self.raw['evidence'] = [{key: evidence[key] for key in ('page', 'chunk_id', 'quote')} for evidence in self.raw['evidence']]
        self.raw['check_scores'] = [{key: check[key] for key in ('index', 'score', 'reason')} for check in self.raw['check_scores']]

    def test_reject_wrong_sum_bounds_precision_index_and_missing_items(self):
        for issue in ('sum', 'bounds', 'precision', 'index', 'missing', 'reason', 'boolean'):
            raw = copy.deepcopy(self.raw)
            if issue == 'sum': raw['score'] += .01
            elif issue == 'bounds': raw['check_scores'][0]['score'] = 100
            elif issue == 'precision': raw['check_scores'][0]['score'] = 1.001
            elif issue == 'index': raw['check_scores'][0]['index'] = 2
            elif issue == 'missing': raw['check_scores'].pop()
            elif issue == 'reason': raw['check_scores'][0]['reason'] = ''
            else: raw['check_scores'][0]['score'] = True
            with self.subTest(issue=issue), self.assertRaises(AssistantError):
                validate_dimension(raw, self.dimension, self.document, self.chunks)

    def test_partial_small_scores_preserve_null_and_known_values(self):
        raw = copy.deepcopy(self.raw)
        raw['score'] = None; raw['status'] = 'unscorable'; raw['check_scores'][0]['score'] = None
        item = validate_dimension(raw, self.dimension, self.document, self.chunks)
        self.assertIsNone(item['score'])
        self.assertIsNone(item['check_scores'][0]['score'])
        self.assertIsNotNone(item['check_scores'][1]['score'])
        raw['evidence'] = []
        with self.assertRaises(AssistantError):
            validate_dimension(raw, self.dimension, self.document, self.chunks)

    def test_result_revalidates_item_text_maximum_and_score(self):
        validate_result(self.payload, self.document, self.rubric)
        for field, value in (('max_score', 99), ('text', '伪造检查项'), ('score', 0)):
            payload = copy.deepcopy(self.payload)
            payload['dimensions'][0]['check_scores'][0][field] = value
            with self.subTest(field=field), self.assertRaises(AssistantError):
                validate_result(payload, self.document, self.rubric)

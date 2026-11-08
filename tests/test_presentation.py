"""Untrusted document content must remain text in the styled HTML surfaces."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from paper_assistant.presentation import render_document_note, render_evidence


class PresentationSafetyTests(unittest.TestCase):
    def test_document_filename_cannot_inject_markup(self):
        document = SimpleNamespace(filename='</strong><img src=x onerror="alert(1)">', source="pdf",
                                   pages=[1], character_count=50, parsing_status="可提取")
        with patch("paper_assistant.presentation.st.markdown") as output:
            render_document_note(document)
        markup = output.call_args.args[0]
        self.assertNotIn("<img", markup)
        self.assertIn("&lt;img", markup)

    def test_evidence_and_chunk_id_cannot_inject_markup(self):
        with patch("paper_assistant.presentation.st.markdown") as output:
            render_evidence({"quote":"<script>alert(1)</script>", "page":2,
                             "chunk_id":'x</figcaption><img src=x onerror="alert(1)">'})
        markup = output.call_args.args[0]
        self.assertNotIn("<script>", markup)
        self.assertNotIn("<img", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("物理第 2 页", markup)

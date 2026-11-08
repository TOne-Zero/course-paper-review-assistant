import hashlib
from dataclasses import replace
from unittest.mock import patch
import unittest
from io import BytesIO
import zipfile

from paper_assistant.config import Settings
from paper_assistant.document_parser import parse_document,validate_document
from paper_assistant.pdf_parser import parse_pdf
from paper_assistant.schemas import AssistantError
from paper_assistant.analysis_service import analyze_document
from paper_assistant.rubrics import load_rubrics
from paper_assistant.report_exporter import export_markdown
from tests.pdf_fixture import make_pdf
from tests.word_fixture import make_docx


class DocumentParserTests(unittest.TestCase):
    def test_pdf_dispatch_preserves_original_behaviour(self):
        content=make_pdf()
        self.assertEqual(parse_document(content,'paper.PDF',Settings()),parse_pdf(content,'paper.PDF',Settings()))

    def test_docx_and_doc_reuse_paged_extraction_and_original_hash(self):
        pdf=make_pdf(texts=['原创测试Word正文。研究问题与方法均用于本地接口检查，不代表真实研究。'*4,'参考文献与表格说明：只验证分页引用和文字提取，不提供学术证据。'*4])
        for filename,content,source in [('论文.DOCX',make_docx(),'docx'),('论文.doc',bytes.fromhex('D0CF11E0A1B11AE1')+b'test','doc')]:
            with self.subTest(filename=filename),patch('paper_assistant.document_parser.convert_word_to_pdf',return_value=pdf) as converter:
                document=parse_document(content,filename,Settings())
                converter.assert_called_once_with(content,'.'+source)
                self.assertEqual(document.source,source);self.assertEqual(document.sha256,hashlib.sha256(content).hexdigest())
                self.assertEqual(len(document.pages),2);self.assertTrue(document.can_analyze)
                self.assertIn('本机转换',document.warnings[0])
                run=analyze_document(document,load_rubrics()[0],Settings(mode='mock'))
                self.assertIn('上传的 Word',export_markdown(run.result).decode())
                self.assertIsNotNone(run.result.data['total_score'])

    def test_file_content_must_match_extension(self):
        cases=[('fake.docx',make_pdf()),('fake.pdf',make_docx()),('fake.doc',make_docx()),('unknown.txt',b'text'),('empty.docx',b''),('broken.docx',b'PKbroken')]
        for name,content in cases:
            with self.subTest(name=name),self.assertRaises(AssistantError):validate_document(content,name)

    def test_arbitrary_or_macro_zip_is_not_a_docx(self):
        for macro in (False,True):
            buffer=BytesIO()
            with zipfile.ZipFile(buffer,'w') as archive:
                archive.writestr('[Content_Types].xml','<Types/>')
                if macro:
                    archive.writestr('word/document.xml','<document/>');archive.writestr('word/vbaProject.bin',b'macro')
            with self.assertRaises(AssistantError):validate_document(buffer.getvalue(),'paper.docx')

    def test_size_limit_is_enforced_before_conversion(self):
        with patch('paper_assistant.document_parser.convert_word_to_pdf') as converter,self.assertRaises(AssistantError):
            parse_document(make_docx(),'paper.docx',replace(Settings(),max_pdf_mb=0))
        converter.assert_not_called()

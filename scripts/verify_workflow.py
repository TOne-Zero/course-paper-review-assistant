"""显式指定授权PDF后验证完整本地流程；外部模型请求始终为零。"""

import argparse
import json
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest

from paper_assistant.api_transport import HTTPChatTransport
from paper_assistant.config import PROJECT_ROOT
from paper_assistant.routes import DEMO_PAGE, PRODUCTION_PAGE
from paper_assistant.document_exporter import export_parsed_document, extract_section_text
from paper_assistant.privacy import clear_managed_files
from paper_assistant.rubrics import export_rubric, load_rubrics
from scripts.verify_demo import export_and_check, upload
from tests.api_responses import envelope, valid_response


def require_clean(app):
    if app.exception:
        raise AssertionError("界面出现异常，请检查本机验证日志。")


def verify(source: Path) -> dict:
    output = PROJECT_ROOT / ".runtime" / "private" / "workflow-check"
    output.mkdir(parents=True, exist_ok=True)
    environment = {"ANALYSIS_MODE": "mock", "PDF_TEXT_ENGINE": "pdfplumber", "MODEL_API_KEY": "", "MODEL_NAME": "", "MODEL_BASE_URL": ""}
    with tempfile.TemporaryDirectory(dir=output, prefix="isolated-") as temp, patch.dict("os.environ", environment), patch(
        "paper_assistant.rubrics.LOCAL_DIRECTORY", Path(temp) / "rubrics"):
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60).run()
        app.switch_page(DEMO_PAGE).run()
        app.selectbox(key="course_rubric").set_value("course_demo").run()
        document = upload(app, source)
        require_clean(app)
        body = extract_section_text(document)
        (output / "逐页解析.json").write_bytes(export_parsed_document(document))
        (output / "正文候选.txt").write_text(body, encoding="utf-8")
        section = next(item for item in document.sections if item.name == "正文")
        assert section.candidates and app.download_button(key="download_body")

        # 在隔离目录验证标准编辑、保存、重载、导出和再次导入，不改动教师本地配置。
        app.toggle(key="teacher_demo").set_value(True).run()
        token = app.session_state["rubric_draft_token"]
        app.number_input(key=f"rubric_{token}_question_score").set_value(16.0).run()
        app.number_input(key=f"rubric_{token}_literature_score").set_value(14.0).run()
        app.button(key="save_rubric").click().run()
        require_clean(app)
        local = load_rubrics(Path(temp) / "rubrics")[0]
        assert local.version == "local-1" and local.total_score == 100
        config = export_rubric(local)
        (output / "隔离测试_课程标准.json").write_bytes(config)
        app.file_uploader(key="import_rubric").set_value(("标准往返测试.json", config, "application/json")).run()
        app.button(key="apply_import_rubric").click().run()
        require_clean(app)
        app.toggle(key="teacher_demo").set_value(False).run()
        app.text_area(key="course_requirements").set_value("仅用于流程检验；本次模拟分数与测试复核意见不构成这篇论文的实际评价。").run()
        app.button(key="start_analysis").click().run()
        require_clean(app)
        initial = app.session_state["analysis_run"].result.data
        assert initial["is_mock"] and len(initial["dimensions"]) == 7

        app.toggle(key="evaluation_review_enabled").set_value(True).run()
        review_token = app.session_state["analysis_run_token"]
        prefix = f"grade_review_{review_token}_question"
        app.number_input(key=prefix + "_score").set_value(10.0).run()
        app.text_area(key=prefix + "_opinion").set_value("【流程测试】仅验证修改保存，不能作为教师实际意见。").run()
        app.text_area(key=prefix + "_rationale").set_value("【流程测试】核对修改记录与导出一致性，非学术质量判断。").run()
        app.button(key=prefix + "_save").click().run()
        app.checkbox(key=f"confirm_all_{review_token}").check().run()
        app.button(key="confirm_evaluation_review").click().run()
        mock = export_and_check(app, "模拟流程_非实际评分", output)
        assert mock["teacher_review"]["confirmed"] and len(mock["teacher_review"]["history"]) == 1
        assert mock["dimensions"][0]["score"] == initial["dimensions"][0]["score"]

        app.button(key="run_format_check").click().run()
        require_clean(app)
        format_report = app.session_state["format_report"]
        assert len(format_report.results) == 3
        app.toggle(key="format_review_enabled").set_value(True).run()
        format_token = app.session_state["format_run_token"]
        rule = format_report.results[0]
        format_prefix = f"format_review_{format_token}_{rule.rule_id}"
        app.selectbox(key=format_prefix + "_status").set_value("无法判断").run()
        app.text_area(key=format_prefix + "_note").set_value("【流程测试】保留系统结果，示范人工复核记录。").run()
        app.button(key=format_prefix + "_save").click().run()
        assert app.session_state["format_report"] == format_report
        assert app.download_button(key="download_format_report")
        (output / "格式检查与测试复核.json").write_text(json.dumps({"automated_report": asdict(format_report),
            "teacher_reviews": app.session_state["format_reviews"], "notice": "复核为流程测试，不代表教师实际结论。"}, ensure_ascii=False, indent=2), encoding="utf-8")

        requests, outcome = [], {"kind": "success"}
        def handler(request):
            requests.append(1)
            if outcome["kind"] == "timeout":
                raise httpx.ReadTimeout("受控超时", request=request)
            response = valid_response(request)
            if outcome["kind"] == "invalid_quote":
                if "observations" in response:
                    response["observations"][0]["evidence"][0]["quote"] = "THIS_QUOTE_IS_ABSENT_8dbb29"
                else:
                    response["evidence"][0]["quote"] = "THIS_QUOTE_IS_ABSENT_8dbb29"
            return httpx.Response(200, json=envelope(response))

        with patch.dict("os.environ", {"MODEL_API_KEY": "controlled-placeholder-only", "MODEL_NAME": "controlled-response-no-external-call",
                                        "MODEL_BASE_URL": "https://controlled.invalid/v1"}), patch(
            "paper_assistant.model_client.HTTPChatTransport",
            side_effect=lambda settings: HTTPChatTransport(settings, transport=httpx.MockTransport(handler))):
            app.switch_page(PRODUCTION_PAGE).run()
            upload(app, source)
            assert app.button(key="start_analysis").disabled and not requests
            next(item for item in app.checkbox if item.key.startswith("cloud_ack_")).check().run()
            app.button(key="start_analysis").click().run()
            controlled = export_and_check(app, "受控接口流程_非真实模型", output)
            assert controlled["total_score"] == 80
            assert controlled["coverage"]["chunk_count"] == len(controlled["coverage"]["processed_chunk_ids"])
            successful_requests = len(requests)
            for kind in ("timeout", "invalid_quote"):
                outcome["kind"] = kind
                app.button(key="start_analysis").click().run()
                require_clean(app)
                assert app.error, "失败时应给出明确错误提示"
                if "analysis_run" in app.session_state:
                    failed = app.session_state["analysis_run"].result.data
                    assert failed["total_score"] is None and all(item["score"] is None for item in failed["dimensions"])

        cleanup_root = Path(temp) / "cleanup"
        (cleanup_root / "uploads").mkdir(parents=True)
        (cleanup_root / "uploads" / "synthetic.pdf").write_bytes(b"synthetic cleanup fixture")
        (cleanup_root / "keep.txt").write_text("keep", encoding="utf-8")
        with patch("paper_assistant.ui.clear_managed_files", side_effect=lambda: clear_managed_files(cleanup_root)):
            app.button(key="clear_private_data").click().run()
        require_clean(app)
        assert app.file_uploader[0].value is None and "parsed_document" not in app.session_state
        assert "teacher_history" not in app.session_state and "format_report" not in app.session_state
        assert (cleanup_root / "keep.txt").exists() and not (cleanup_root / "uploads").exists()

        summary = {
            "verified_at_utc": datetime.now(timezone.utc).isoformat(), "filename": source.name, "sha256": document.sha256,
            "pages": len(document.pages), "extractable_pages": len(document.reliable_pages),
            "body_start_page": section.candidates[0].start_page, "body_end_page": section.candidates[-1].end_page, "body_characters": len(body),
            "rubric_save_import_export": True, "mock_review_confirm_export": True, "format_review_export": True,
            "format_results": [{"rule": item.name, "status": item.status, "evidence_pages": [e.page for e in item.evidence],
                                "uncertain_pages": list(item.uncertain_pages)} for item in format_report.results],
            "controlled_api": {"passed": True, "successful_requests": successful_requests, "chunk_count": controlled["coverage"]["chunk_count"],
                               "batches": controlled["coverage"]["batch_count"], "timeout_rejected": True, "invalid_quote_rejected": True},
            "cleanup_session_and_isolated_files": True, "external_model_calls": 0, "live_api_tested": False,
            "limitations": ["无真实API配置，受控响应只验证接口，不验证实际模型评分质量。", "复杂图表、公式与图像中的信息不保证完整提取。",
                            "自动化操作界面并使用同一导出函数写盘重读；未人工点击浏览器下载。", "所有分数与教师意见都是测试数据，不是论文实际评价。"],
        }
        (output / "流程验证记录.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary


def main():
    parser = argparse.ArgumentParser(description="本地检验授权PDF的完整流程（不连接外部模型服务）")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.pdf), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

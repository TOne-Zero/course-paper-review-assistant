"""原创 PDF 的上传→评价→教师修改→确认→双格式导出验证；从不连接外部模型。"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest

from paper_assistant.api_transport import HTTPChatTransport
from paper_assistant.config import PROJECT_ROOT
from paper_assistant.routes import DEMO_PAGE, PRODUCTION_PAGE
from paper_assistant.report_exporter import export_json, export_markdown
from tests.api_responses import envelope, valid_response


OUTPUT = PROJECT_ROOT / ".runtime" / "private" / "demo-verification"


def export_and_check(app, prefix, output=OUTPUT):
    assert not app.exception, "界面发生异常"
    run = app.session_state["analysis_run"]
    history = app.session_state["teacher_history"] if "teacher_history" in app.session_state else []
    confirmation = app.session_state["teacher_confirmation"] if "teacher_confirmation" in app.session_state else None
    json_bytes = export_json(run.result, history, confirmation)
    markdown_bytes = export_markdown(run.result, history, confirmation)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / f"{prefix}.json"
    md_path = output / f"{prefix}.md"
    json_path.write_bytes(json_bytes)
    md_path.write_bytes(markdown_bytes)
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["evaluation_id"] == run.result.data["evaluation_id"]
    assert all(e["verified"] is True for item in saved["dimensions"] for e in item["evidence"])
    assert "最终成绩由教师确定" in md_path.read_text(encoding="utf-8")
    assert app.download_button(key="download_evaluation_markdown")
    assert app.download_button(key="download_evaluation_json")
    return saved


def upload(app, source=None):
    is_builtin = source is None
    source = source or PROJECT_ROOT / "examples" / "演示论文_原创虚构.pdf"
    app.file_uploader[0].set_value((source.name, source.read_bytes(), "application/pdf")).run()
    document = app.session_state["parsed_document"]
    assert document.can_analyze
    if is_builtin:
        assert len(document.pages) == len(document.reliable_pages) == 3
    return document


def main():
    environment = {"ANALYSIS_MODE": "mock", "MODEL_API_KEY": "", "MODEL_NAME": "", "MODEL_BASE_URL": ""}
    with patch.dict("os.environ", environment):
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
        app.switch_page(DEMO_PAGE).run()
        document = upload(app)
        app.text_area(key="course_requirements").set_value("演示课程：核对研究问题、方法、分析和局限，不将虚构数据用作实际结论。").run()
        app.button(key="start_analysis").click().run()
        initial = app.session_state["analysis_run"].result.data["dimensions"][0]["score"]
        app.toggle(key="evaluation_review_enabled").set_value(True).run()
        token = app.session_state["analysis_run_token"]
        prefix = f"grade_review_{token}_question"
        app.number_input(key=prefix + "_score").set_value(10.0).run()
        app.text_area(key=prefix + "_opinion").set_value("演示复核：研究问题应再限定讨论时长和提问类型。").run()
        app.text_area(key=prefix + "_rationale").set_value("已核对第1页研究问题及第3页局限；这是演示意见，未证明研究有效。").run()
        app.button(key=prefix + "_save").click().run()
        app.checkbox(key=f"confirm_all_{token}").check().run()
        app.button(key="confirm_evaluation_review").click().run()
        mock = export_and_check(app, "模拟模式_教师复核报告")
        assert mock["is_mock"] and mock["teacher_review"]["confirmed"]
        assert mock["dimensions"][0]["score"] == initial
        assert mock["teacher_review"]["dimensions"][0]["score"] == 10.0
        assert len(mock["teacher_review"]["history"]) == 1

        requests = []
        def handler(request):
            requests.append(1)  # 只记计数，不留存请求正文或 Authorization。
            return httpx.Response(200, json=envelope(valid_response(request)))
        with patch.dict("os.environ", {"MODEL_API_KEY": "controlled-placeholder-only", "MODEL_NAME": "controlled-response-no-external-call",
                                        "MODEL_BASE_URL": "https://controlled.invalid/v1"}), patch(
            "paper_assistant.model_client.HTTPChatTransport",
            side_effect=lambda settings: HTTPChatTransport(settings, transport=httpx.MockTransport(handler))):
            controlled_app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
            controlled_app.switch_page(PRODUCTION_PAGE).run()
            upload(controlled_app)
            controlled_app.text_area(key="course_requirements").set_value("受控协议验证：本次返回由测试程序构造，不是真实模型评价。").run()
            assert controlled_app.button(key="start_analysis").disabled and not requests
            next(item for item in controlled_app.checkbox if item.key.startswith("cloud_ack_")).check().run()
            controlled_app.button(key="start_analysis").click().run()
            controlled = export_and_check(controlled_app, "受控HTTP响应_非真实模型报告")
            assert controlled["total_score"] == 80
            assert len(requests) == len(controlled["dimensions"])

        record = {
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "method": "Streamlit AppTest 实际上传原创PDF，操作界面，调用同一导出函数写盘后重新读取；未人工点击浏览器下载。",
            "input": {"filename": document.filename, "pages": len(document.pages), "sha256": document.sha256},
            "mock": {"passed": True, "ai_total": mock["total_score"], "review_total": mock["teacher_review"]["total_score"],
                     "teacher_history_entries": len(mock["teacher_review"]["history"]), "confirmed": True, "external_calls": 0},
            "controlled_api": {"passed": True, "mock_transport_calls": len(requests), "external_calls": 0,
                               "scope": "真实适配器的请求、响应、证据校验、界面和导出；使用HTTPX MockTransport。"},
            "live_provider": {"tested": False, "reason": "当前未配置真实API密钥、模型名和服务地址；未验证服务连通性、兼容性、耗时、费用或评分质量。"},
            "outputs": ["模拟模式_教师复核报告.md", "模拟模式_教师复核报告.json", "受控HTTP响应_非真实模型报告.md", "受控HTTP响应_非真实模型报告.json"],
        }
        (OUTPUT / "验证记录.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

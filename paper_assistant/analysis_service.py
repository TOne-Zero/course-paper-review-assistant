"""编排解析→模型→校验，保证界面只能拿到校验后的完整运行结果。"""

from paper_assistant.config import Settings
from paper_assistant.model_client import create_model_client
from paper_assistant.document_parser import parse_document
from paper_assistant.schemas import AnalysisRun, AssistantError, ParsedDocument, Rubric
from paper_assistant.validator import validate_result


def analyze_document(document: ParsedDocument, rubric: Rubric, settings: Settings, *, course_requirements: str = "",
                     allow_cloud: bool = False, client=None, progress=None, on_stream=None) -> AnalysisRun:
    if not document.can_analyze:
        raise AssistantError("可用文字不足，无法判断；请核对解析概况，或上传包含正文的Word/可搜索文字的PDF。")
    if settings.mode == "real" and not allow_cloud:
        raise AssistantError("尚未确认向所选模型服务发送论文文本，未发起调用。")
    if not isinstance(course_requirements, str) or len(course_requirements) > 6000:
        raise AssistantError("课程要求需为不超过 6000 字符的文本；没有截断内容。")
    client = client or create_model_client(settings, course_requirements=course_requirements, progress=progress, on_stream=on_stream)
    payload = client.evaluate(document, rubric)
    if not isinstance(payload, dict):
        raise AssistantError("模型适配器未返回结构化对象，已拒绝结果。")
    if payload.get("mode") != settings.mode:
        raise AssistantError("适配器返回的运行模式与选择不一致，未采用结果。")
    if payload.get("course_requirements") != course_requirements:
        raise AssistantError("适配器结果中的课程要求与本次输入不一致，未采用结果。")
    result = validate_result(payload, document, rubric)
    return AnalysisRun(document=document, rubric=rubric, result=result)


def analyze_pdf(content: bytes, filename: str, rubric: Rubric, settings: Settings) -> AnalysisRun:
    document = parse_document(content, filename, settings)
    return analyze_document(document, rubric, settings)

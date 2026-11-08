"""有界批量输入与独立评阅状态；不自动发起模型请求。"""

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import PurePath
import re
import zipfile

from paper_assistant.document_parser import PARSER_VERSION, parse_document
from paper_assistant.report_exporter import export_json, export_markdown
from paper_assistant.schemas import AssistantError


MAX_BATCH_FILES = 10
MAX_BATCH_BYTES = 50 * 1024 * 1024
RUN_KEYS = ("input_signature", "analysis_run", "analysis_run_token", "teacher_history", "teacher_confirmation", "analysis_error")
PAPER_KEYS = ("parse_signature", "parsed_document", "parse_error", *RUN_KEYS,
              "format_input_signature", "format_report", "format_reviews", "format_run_token", "format_checked_at")


@dataclass(frozen=True)
class BatchPaper:
    key: str
    name: str
    content: bytes


def collect_uploads(uploads) -> list[BatchPaper]:
    files = uploads if isinstance(uploads, list) else [uploads] if uploads is not None else []
    if len(files) > MAX_BATCH_FILES:
        raise AssistantError(f"每批最多 {MAX_BATCH_FILES} 篇，请移除多余文件。")
    if sum(file.size for file in files) > MAX_BATCH_BYTES:
        raise AssistantError("本批次超过 50 MB，请减少或压缩论文文件。")
    papers = []
    occurrences = {}
    for file in files:
        content = file.getvalue()
        digest = hashlib.sha256(file.name.encode("utf-8") + b"\0" + content).hexdigest()
        number = occurrences.get(digest, 0)
        occurrences[digest] = number + 1
        papers.append(BatchPaper(f"{digest}-{number}", file.name, content))
    return papers


def parse_signature(paper: BatchPaper, settings):
    return (hashlib.sha256(paper.content).hexdigest(), paper.name,
            (settings.max_pdf_mb, settings.max_pdf_pages, settings.max_text_characters,
             settings.min_page_text_characters, settings.min_document_text_characters, settings.pdf_text_engine), PARSER_VERSION)


def sync_batch(state, keys: list[str], active: str | None, context):
    """先存当前论文，再恢复选择的论文；共同评分条件变化会清除全批旧评分。"""
    previous = state.get("batch_active")
    papers = state.setdefault("batch_papers", {})
    if previous in keys:
        papers[previous] = {key: state[key] for key in PAPER_KEYS if key in state}
    papers = {key: papers.get(key, {}) for key in keys}
    if state.get("batch_context") != context:
        for snapshot in papers.values():
            for key in RUN_KEYS:
                snapshot.pop(key, None)
        state["batch_context"] = context
    state["batch_papers"] = papers
    state["batch_active"] = active
    return papers


def parse_batch(papers, snapshots, settings, *, parser=None):
    parser = parser or parse_document
    for paper in papers:
        snapshot = snapshots[paper.key]
        signature = parse_signature(paper, settings)
        if snapshot.get("parse_signature") == signature:
            continue
        snapshot.clear()
        snapshot["parse_signature"] = signature
        try:
            snapshot["parsed_document"] = parser(paper.content, paper.name, settings)
        except AssistantError as error:
            snapshot["parse_error"] = str(error)
        except Exception:
            snapshot["parse_error"] = "文档解析失败，请更换文件。"


def activate_paper(state, snapshot):
    for key in PAPER_KEYS:
        if key in snapshot:
            state[key] = snapshot[key]
        else:
            state.pop(key, None)


def store_active(state):
    active = state.get("batch_active")
    if active is not None:
        state.setdefault("batch_papers", {})[active] = {key: state[key] for key in PAPER_KEYS if key in state}


def evaluation_signature(signature, rubric, requirements, settings):
    return (signature, rubric, requirements, settings, hashlib.sha256(settings.model_api_key.encode()).hexdigest())


def analyze_batch(papers, snapshots, rubric, settings, requirements, *, allow_cloud, analyzer, progress=None):
    if settings.mode == "real" and not allow_cloud:
        raise AssistantError("请先确认本批次论文发送。")
    for index, paper in enumerate(papers, 1):
        snapshot = snapshots[paper.key]
        if progress:
            progress(index, len(papers), paper.name)
        document = snapshot.get("parsed_document")
        if snapshot.get("analysis_run") is not None or document is None or not document.can_analyze:
            continue
        snapshot.pop("analysis_error", None)
        try:
            snapshot["analysis_run"] = analyzer(document, rubric, settings,
                course_requirements=requirements, allow_cloud=allow_cloud,
                progress=(lambda message: progress(index, len(papers), paper.name + " · " + message)) if progress else None)
            snapshot["input_signature"] = evaluation_signature(snapshot["parse_signature"], rubric, requirements, settings)
            from uuid import uuid4
            snapshot["analysis_run_token"] = uuid4().hex
        except AssistantError as error:
            snapshot["analysis_error"] = str(error)
        except Exception:
            snapshot["analysis_error"] = "分析失败，可选择此论文单独重试。"


def export_batch(papers, snapshots) -> bytes:
    """内存ZIP：序号防止同名覆盖，所有名称仅使用安全文件名，不写磁盘。"""
    output = BytesIO()
    manifest = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, paper in enumerate(papers, 1):
            snapshot = snapshots.get(paper.key, {})
            run = snapshot.get("analysis_run")
            entry = {"序号": index, "文件": paper.name, "状态": "已分析" if run else "未分析",
                     "原因": snapshot.get("analysis_error") or snapshot.get("parse_error") or ""}
            if run is not None:
                # Windows、POSIX 分隔符均移除；序号保证重名文件不覆盖。
                stem = PurePath(paper.name.replace("\\", "/")).stem
                safe = re.sub(r'[^\w\u4e00-\u9fff .-]', "_", stem).strip(" .")[:70] or "论文"
                prefix = f"{index:02d}_{safe}"
                history, confirmation = snapshot.get("teacher_history", []), snapshot.get("teacher_confirmation")
                archive.writestr(prefix + ".md", export_markdown(run.result, history, confirmation))
                archive.writestr(prefix + ".json", export_json(run.result, history, confirmation))
                entry["报告"] = [prefix + ".md", prefix + ".json"]
            manifest.append(entry)
        archive.writestr("批次清单.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return output.getvalue()

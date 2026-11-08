"""校验结构、分数、逐页原文与片段来源；无效引用绝不进入报告。"""

import json
import math
import re
from datetime import datetime

from paper_assistant.evaluation_contract import MOCK_NOTICE, REAL_NOTICE, total_score
from paper_assistant.rubrics import rubric_to_dict
from paper_assistant.schemas import AssistantError, ValidatedResult, document_metadata


class EvidenceValidationError(AssistantError):
    pass


class ModelJSONError(AssistantError):
    """模型格式错误，可请求模型重新生成，不能补造缺失字段。"""
    pass


class ModelStructureError(AssistantError):
    """语法正确，但模型的必填结构或分值不符合本维度约定。"""
    pass


def _require(condition):
    if not condition:
        raise ValueError


def _text(value, maximum=6000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _number(value):
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        return False


def parse_model_json(content: str) -> dict:
    def unique(pairs):
        data = {}
        for key, value in pairs:
            _require(key not in data)
            data[key] = value
        return data
    try:
        _require(isinstance(content, str) and len(content) <= 16 * 1024 * 1024)
        content = content.lstrip('\ufeff').strip()
        content = re.sub(r'\A(?:<think>[\s\S]*?</think>\s*)+', '', content,flags=re.IGNORECASE).strip()
        fenced = re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```', content, flags=re.IGNORECASE)
        if fenced:
            content = fenced.group(1).strip()
        # 只取有明确边界的原样单个对象；不修补对象内部、不挑选多个候选。
        first,last=content.find('{'),content.rfind('}')
        if first>=0 and last>=first and (first or last<len(content)-1):
            prefix,suffix=content[:first],content[last+1:]
            if len(prefix)<=256 and len(suffix)<=256 and not any(c in prefix+suffix for c in '{}[]'):
                prefix=re.sub(r'```(?:json)?','',prefix,flags=re.IGNORECASE).strip()
                suffix=suffix.replace('```','').strip()
                if not re.fullmatch(r'(?:\d+(?:\.\d+)?|true|false|null)',prefix or suffix,flags=re.IGNORECASE):
                    content=content[first:last+1]
        result = json.loads(content, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _require(isinstance(result, dict))
        return result
    except (ValueError, TypeError, RecursionError):
        raise ModelJSONError("模型未返回单个有效的 JSON 对象，或包含重复字段；本次内容未采用，可重新评阅。") from None


def validate_evidence(evidence, document, chunks, *, require_any: bool) -> list[dict]:
    try:
        _require(isinstance(evidence, list) and len(evidence) <= 20)
        _require(bool(evidence) or not require_any)
        pages = {page.number: page.text for page in document.reliable_pages}
        sources = {chunk.id: chunk for chunk in chunks}
        verified = []
        for item in evidence:
            _require(isinstance(item, dict) and set(item) == {"page", "chunk_id", "quote"})
            page, quote, chunk_id = item["page"], item["quote"], item["chunk_id"]
            _require(type(page) is int and page in pages and chunk_id in sources)
            chunk = sources[chunk_id]
            _require(chunk.page == page and _text(quote, 800) and quote in chunk.text and quote in pages[page])
            verified.append({"page": page, "chunk_id": chunk_id, "quote": quote,
                             "verified": True, "note": "程序已核对原文与物理页码；不代表本证据能充分支持评分观点。"})
        return verified
    except (ValueError, TypeError, KeyError, AttributeError):
        raise EvidenceValidationError("模型引用的页码、片段或原文未通过校验；本项结果未采用。") from None


def validate_dimension(payload: dict, dimension, document, chunks) -> dict:
    stage='必填字段'
    try:
        expected = {"dimension_id", "status", "score", "max_score", "reason", "evidence", "suggestions", "needs_teacher_review"}
        if dimension.checklist_scores:
            expected.add('check_scores')
        _require(isinstance(payload, dict) and set(payload) == expected)
        stage='维度标识与满分'
        _require(payload["dimension_id"] == dimension.id)
        _require(_number(payload["max_score"]) and payload["max_score"] == dimension.max_score)
        _require(payload["status"] in {"scored", "unscorable"})
        score = payload["score"]
        stage='维度分数范围与精度'
        if payload["status"] == "scored":
            _require(_number(score) and 0 <= score <= dimension.max_score and abs(score - round(score, 2)) < 1e-8)
        else:
            _require(score is None)
        check_scores = []
        if dimension.checklist_scores:
            stage='小项数量'
            checks = payload['check_scores']
            _require(isinstance(checks, list) and len(checks) == len(dimension.checklist))
            for index, (item, maximum, text) in enumerate(zip(checks, dimension.checklist_scores, dimension.checklist), 1):
                stage='小项顺序与理由'
                _require(isinstance(item, dict) and set(item) == {'index', 'score', 'reason'})
                _require(type(item['index']) is int and item['index'] == index and _text(item['reason'], 6000))
                value = item['score']
                stage='小项分数范围与精度'
                _require(value is None or (_number(value) and 0 <= value <= maximum and abs(value - round(value, 2)) < 1e-8))
                check_scores.append(dict(item, text=text, max_score=maximum))
            subtotal = None if any(item['score'] is None for item in check_scores) else round(sum(item['score'] for item in check_scores), 2)
            stage='小项合计与维度分数'
            _require(score == subtotal and (payload['status'] == 'scored') is (subtotal is not None))
        stage='评分理由与复核标记'
        _require(_text(payload["reason"]) and type(payload["needs_teacher_review"]) is bool)
        suggestions = payload["suggestions"]
        stage='修改建议'
        _require(isinstance(suggestions, list) and 1 <= len(suggestions) <= 10 and all(_text(item, 2000) for item in suggestions))
        verified = validate_evidence(payload["evidence"], document, chunks, require_any=score is not None or any(item['score'] is not None for item in check_scores))
        _require(score is not None or payload["needs_teacher_review"] is True)
        result = dict(payload, name=dimension.name, required=dimension.required, evidence=verified, error_code=None,
                    evidence_status="verified" if verified else "no_verified_evidence", opinion_status="未由程序核实的参考意见")
        if dimension.checklist_scores:
            result['check_scores'] = check_scores
        return result
    except AssistantError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ModelStructureError(f"模型返回的{stage}未通过校验；本项结果未采用。") from None


def validate_result(payload, document, rubric) -> ValidatedResult:
    from paper_assistant.paper_context import PaperChunk
    try:
        _require(isinstance(payload, dict) and document.can_analyze)
        _require(payload["schema_version"] == "2.0" and payload["mode"] in {"mock", "real"})
        _require(isinstance(payload["evaluation_id"], str) and len(payload["evaluation_id"]) == 32)
        _require(payload["is_mock"] is (payload["mode"] == "mock"))
        _require(payload["notice"] == (MOCK_NOTICE if payload["mode"] == "mock" else REAL_NOTICE))
        _require(payload["teacher_decision_required"] is True and _text(payload["summary"]))
        _require(datetime.fromisoformat(payload["generated_at"]).tzinfo is not None)
        _require(payload["document"] == document_metadata(document))
        _require(payload["rubric"] == {"id": rubric.id, "name": rubric.name, "version": rubric.version})
        _require(payload["rubric_snapshot"] == rubric_to_dict(rubric))
        _require(isinstance(payload["course_requirements"], str) and len(payload["course_requirements"]) <= 6000)
        model = payload["model"]
        _require(set(model) == {"name", "provider", "service"} and all(_text(v, 500) for v in model.values()))
        coverage = payload["coverage"]
        _require(coverage["page_numbers"] == [page.number for page in document.reliable_pages])
        _require(coverage["excluded_pages"] == [{"page": page.number, "reason": page.reason} for page in document.pages if page not in document.reliable_pages])
        _require(coverage["input_characters"] == sum(len(page.text) for page in document.reliable_pages))
        chunks = []
        manifest = coverage["chunk_manifest"]
        pages = {page.number: page.text for page in document.reliable_pages}
        ends = {page: 0 for page in pages}
        for item in manifest:
            page, start, end = item["page"], item["start"], item["end"]
            _require(type(page) is int and page in pages and type(start) is int and type(end) is int)
            _require(start == ends[page] and start < end <= len(pages[page]))
            ends[page] = end
            chunks.append(PaperChunk(item["id"], page, start, end, pages[page][start:end]))
        _require(all(ends[page] == len(text) for page, text in pages.items()))
        _require(len({c.id for c in chunks}) == len(chunks) == coverage["chunk_count"])
        processed = coverage["processed_chunk_ids"]
        _require(isinstance(processed, list) and len(set(processed)) == len(processed) and set(processed).issubset({c.id for c in chunks}))
        items = payload["dimensions"]
        _require(isinstance(items, list) and len(items) == len(rubric.dimensions))
        expected = {item.id: item for item in rubric.dimensions}
        seen = set()
        for item in items:
            dimension_id = item["dimension_id"]
            _require(dimension_id in expected and dimension_id not in seen)
            seen.add(dimension_id)
            dimension = expected[dimension_id]
            raw = {key: item[key] for key in ("dimension_id", "status", "score", "max_score", "reason", "evidence", "suggestions", "needs_teacher_review")}
            if dimension.checklist_scores:
                raw['check_scores'] = [{key: check[key] for key in ('index', 'score', 'reason')} for check in item['check_scores']]
            raw["evidence"] = [{key: evidence[key] for key in ("page", "chunk_id", "quote")} for evidence in item["evidence"]]
            validated = validate_dimension(raw, dimension, document, chunks)
            _require(item["name"] == dimension.name and item["required"] is dimension.required)
            _require(item["evidence"] == validated["evidence"] and item["evidence_status"] == validated["evidence_status"])
            _require(item["opinion_status"] == "未由程序核实的参考意见")
            if dimension.checklist_scores:
                _require(item['check_scores'] == validated['check_scores'])
            if item["score"] is not None:
                _require(set(processed) == {c.id for c in chunks})
        _require(payload["total_score"] is None or _number(payload["total_score"]))
        _require(payload["total_score"] == total_score(items) and payload["max_total_score"] == rubric.total_score)
        data = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        raise AssistantError("分析结果未通过校验（结构、分值、合计或原文引用不一致），已阻止展示和导出。") from None
    return ValidatedResult(data)

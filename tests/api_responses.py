"""受控响应只用于测试，不在应用中冒充真实 API 结果。"""

import json
from paper_assistant.rubric_defaults import demonstration_scores


def valid_response(request):
    body = json.loads(request.content)
    data = json.loads(body["messages"][1]["content"])
    if "dimensions" in data:
        chunks = data["untrusted_paper_fragments"]
        return {"observations": [{"dimension_id": dimension["id"], "note": "受控测试观察，非真实模型判断。",
                "evidence": [{"page": chunks[0]["page"], "chunk_id": chunks[0]["id"], "quote": chunks[0]["text"][:100]}]}
                for dimension in data["dimensions"]]}
    dimension = data["dimension"]
    if "untrusted_paper_fragments" in data:
        chunk = data["untrusted_paper_fragments"][0]
        evidence = {"page": chunk["page"], "chunk_id": chunk["id"], "quote": chunk["text"][:100]}
    else:
        source = data["untrusted_extracted_observations"][0]["records"][0]["evidence"][0]
        evidence = {key: source[key] for key in ("page", "chunk_id", "quote")}
    result = {"dimension_id": dimension["id"], "status": "scored", "score": round(dimension["max_score"] * 0.8, 2),
            "max_score": dimension["max_score"], "reason": "受控响应：只验证接口与引用校验，不代表真实评分质量。",
            "evidence": [evidence], "suggestions": ["请补充与研究问题对应的材料出处，再请教师核对。"], "needs_teacher_review": True}
    if dimension.get('checklist_scores'):
        result['check_scores'] = [{'index': i + 1, 'score': value, 'reason': '受控小项响应，仅验证链路。'}
                                  for i, value in enumerate(demonstration_scores(dimension['checklist_scores'], .8))]
        result['score'] = round(sum(item['score'] for item in result['check_scores']), 2)
    return result


def envelope(content, *, finish_reason="stop"):
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content}}]}

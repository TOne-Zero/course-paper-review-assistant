"""可替换评价接口：模拟实现与 Chat Completions 兼容实现。"""

import json
from dataclasses import replace
from typing import Protocol

from paper_assistant.api_transport import HTTPChatTransport, ModelCallError, OutputTruncatedError, service_label
from paper_assistant.config import Settings
from paper_assistant.evaluation_contract import MOCK_NOTICE, build_result, unscored
from paper_assistant.model_prompts import DIMENSION_SCHEMA, MAP_SCHEMA, dimension_schema, make_map_messages, make_messages
from paper_assistant.paper_context import plan_evaluation
from paper_assistant.schemas import AssistantError
from paper_assistant.rubric_defaults import demonstration_scores
from paper_assistant.validator import EvidenceValidationError, ModelJSONError, ModelStructureError, parse_model_json, validate_dimension, validate_evidence


class ModelClient(Protocol):
    def evaluate(self, document, rubric) -> dict:
        """返回待校验结果；不得执行论文中的指令或输出未经核验的证据。"""
        ...


class MockModelClient:
    def __init__(self, settings: Settings | None = None, *, course_requirements="", progress=None):
        self.settings = settings or Settings()
        self.course_requirements = course_requirements
        self.progress = progress or (lambda _: None)

    def evaluate(self, document, rubric) -> dict:
        plan = plan_evaluation(document, rubric, self.settings)
        ratios = (0.80, 0.75, 0.85, 0.80, 0.70)
        dimensions = []
        for index, dimension in enumerate(rubric.dimensions):
            self.progress(f"模拟评价：{dimension.name}")
            chunk = plan.chunks[index % len(plan.chunks)]
            raw = {"dimension_id": dimension.id, "status": "scored",
                   "score": round(dimension.max_score * ratios[index % len(ratios)], 2), "max_score": dimension.max_score,
                   "reason": "【模拟说明】按固定比例生成参考分，未进行实际质量判断。",
                   "evidence": [{"page": chunk.page, "chunk_id": chunk.id, "quote": chunk.text[:160]}],
                   "suggestions": [f"【模拟建议】请对照“{dimension.name}”核对：{dimension.description}",
                                   "【模拟建议】补充能对应论点的材料和出处，再请教师复核。"],
                   "needs_teacher_review": True}
            if dimension.checklist_scores:
                raw['check_scores'] = [{'index': i + 1, 'score': value,
                                        'reason': '【模拟说明】固定比例演示，未评价本条细则的实际完成情况。'}
                                       for i, value in enumerate(demonstration_scores(dimension.checklist_scores, ratios[index % len(ratios)]))]
                raw['score'] = round(sum(item['score'] for item in raw['check_scores']), 2)
            dimensions.append(validate_dimension(raw, dimension, document, plan.chunks))
        coverage = dict(plan.coverage, processed_chunk_ids=[chunk.id for chunk in plan.chunks], actual_calls=0)
        coverage["note"] += " 当前是模拟演示，未请求模型，也未实际评估全文质量。"
        return build_result(document, rubric, mode="mock", model={"name": "mock-local-v2", "provider": "mock", "service": "local-only"},
                            dimensions=dimensions, coverage=coverage, course_requirements=self.course_requirements)


class OpenAICompatibleModelClient:
    def __init__(self, settings: Settings, *, transport=None, course_requirements="", progress=None, on_stream=None):
        self.settings = settings
        self.transport = transport or (HTTPChatTransport(settings, on_stream=on_stream) if on_stream else HTTPChatTransport(settings))
        self.course_requirements = course_requirements
        self.progress = progress or (lambda _: None)

    def evaluate(self, document, rubric) -> dict:
        plan = plan_evaluation(document, rubric, self.settings)
        coverage = dict(plan.coverage)
        def complete(transport, messages, schema):
            before = getattr(transport,'requests_sent',None)
            if type(before) is not int:before=None
            try:
                return transport.complete(messages,schema)
            finally:
                coverage['actual_calls'] += transport.requests_sent-before if before is not None else 1
        # 在发送任何内容前，检查所有原文批次/短文请求的字符预算。
        preflight = ([make_map_messages(document, rubric, batch, self.course_requirements) for batch in plan.batches]
                     if len(plan.batches) > 1 else
                     [make_messages(document, rubric, dimension, plan.chunks, self.course_requirements) for dimension in rubric.dimensions])
        if any(len(json.dumps(messages, ensure_ascii=False)) > self.settings.model_max_prompt_characters for messages in preflight):
            raise AssistantError("原文或课程标准超过提示预算，尚未发送论文；请调整分段、提示预算或课程要求。未截断内容。")
        observations = None
        if len(plan.batches) > 1:
            observations = {dimension.id: [] for dimension in rubric.dimensions}
            for index, (batch, messages) in enumerate(zip(plan.batches, preflight), 1):
                self.progress(f"逐批读取全部可用文字：{index}/{len(plan.batches)}")
                retried_errors=set()
                for attempt in range(3):
                    try:
                        response = parse_model_json(complete(self.transport,messages,MAP_SCHEMA))
                        # 先核对本批全部引用，再提交任何观察；失败重试不混入首轮数据。
                        if isinstance(response.get('observations'), list):
                            for observation in response['observations']:
                                if isinstance(observation, dict) and 'evidence' in observation:
                                    validate_evidence(observation['evidence'], document, batch, require_any=False)
                        break
                    except (OutputTruncatedError, EvidenceValidationError, ModelJSONError, ModelStructureError) as error:
                        remaining = len(plan.batches) - index + len(rubric.dimensions)
                        if type(error) in retried_errors or attempt>=2 or coverage['actual_calls'] + remaining >= self.settings.model_max_calls:
                            raise
                        retried_errors.add(type(error))
                        if isinstance(error, (ModelJSONError,ModelStructureError)):
                            notice = '返回格式不符合JSON要求，重新生成一次'
                            instruction = '上次回复不是单个有效JSON对象或有重复字段。请重新输出本批完整JSON，严格使用系统给定结构，只输出一个对象；禁止Markdown、重复字段、额外说明，字符串内换行请转义；不要遗漏本批原文或编造证据。'
                        elif isinstance(error, EvidenceValidationError):
                            notice = '引用未通过核验，按原文候选重新提取一次'
                            instruction = '上次引用未通过逐字核验。重新输出本批完整JSON，evidence只能逐字复制evidence_candidates中的quote和对应page、chunk_id，不改标点、不拼接；无依据可不返回该维度。'
                        else:
                            notice = '提取被服务商截断，精简提取格式重试一次'
                            instruction = '上次输出未完成。只提取每维最关键的一条观察，note不超过80字、evidence一条连续原文；不要输出重复解释，不要省略已提供批次。'
                        self.progress(f'第{index}批{notice}')
                        messages = [*messages, {'role': 'user', 'content': instruction}]
                if set(response) != {"observations"} or not isinstance(response["observations"], list):
                    raise AssistantError("分段抽取输出无效，已停止评分；未跳过失败批次。")
                known = set(observations)
                notes = {dimension_id: [] for dimension_id in known}
                if len(response["observations"]) > len(known) * 3:
                    raise AssistantError("分段抽取记录过多，已停止；未静默删减。")
                for observation in response["observations"]:
                    if (not isinstance(observation, dict) or set(observation) != {"dimension_id", "note", "evidence"}
                            or not isinstance(observation["dimension_id"], str) or observation["dimension_id"] not in known
                            or not isinstance(observation["note"], str)
                            or not observation["note"].strip() or len(observation["note"]) > 4000):
                        raise AssistantError("分段抽取的字段或维度无效，已停止评分。")
                    evidence = validate_evidence(observation["evidence"], document, batch, require_any=False)
                    notes[observation["dimension_id"]].append({"note": observation["note"], "evidence": evidence})
                for dimension_id in known:
                    observations[dimension_id].append({"batch": index, "chunk_ids": [chunk.id for chunk in batch],
                        "records": notes[dimension_id], "notice": "本批无记录时仅表示未抽取证据，不代表论文没有相应内容。"})
                coverage["processed_chunk_ids"].extend(chunk.id for chunk in batch)
            if any(len(json.dumps(items, ensure_ascii=False)) > self.settings.model_max_synthesis_characters for items in observations.values()):
                raise AssistantError("全部分段证据超过合成预算，已停止评分；没有静默删减。论文文字已按批发送，请调整预算后再试。")
        dimensions, diagnostics = [], []
        stopped = None
        for dimension_index, dimension in enumerate(rubric.dimensions):
            if stopped:
                dimensions.append(unscored(dimension, "前序请求失败，本轮未调用本维度；请检查服务后重新评价。", "NOT_CALLED"))
                continue
            self.progress(f"生成维度参考评价：{dimension.name}")
            try:
                messages = make_messages(document, rubric, dimension, plan.chunks, self.course_requirements,
                                         observations=None if observations is None else observations[dimension.id])
                if observations is not None:
                    full_messages = make_messages(document, rubric, dimension, plan.chunks, self.course_requirements)
                    if len(json.dumps(full_messages,ensure_ascii=False)) <= self.settings.model_max_prompt_characters:
                        messages = full_messages
                        coverage['synthesis_source'] = 'full_reliable_text'
                transport = self.transport
                retried_errors=set()
                for attempt in range(3):
                    try:
                        payload = parse_model_json(complete(transport,messages,dimension_schema(dimension)))
                        checked = validate_dimension(payload, dimension, document, plan.chunks)
                        break
                    except (OutputTruncatedError, EvidenceValidationError, ModelJSONError, ModelStructureError) as error:
                        remaining = len(rubric.dimensions) - dimension_index - 1
                        if type(error) in retried_errors or attempt>=2 or coverage['actual_calls'] + remaining >= self.settings.model_max_calls:
                            raise
                        retried_errors.add(type(error))
                        if isinstance(error, OutputTruncatedError):
                            if not self.settings.model_max_output_tokens:
                                messages = [*messages, {'role': 'user', 'content': '服务商截断了上次回复。请精简理由与建议，保持所有小项和有效原文证据，重新输出完整JSON；应用没有设置输出token上限。'}]
                                notice = '服务商截断输出，精简回复重试一次（未设置本地输出上限）。'
                            else:
                                new_limit = min(32768, max(8192, self.settings.model_max_output_tokens * 2))
                                if new_limit <= self.settings.model_max_output_tokens or not isinstance(self.transport, HTTPChatTransport):
                                    raise
                                transport = HTTPChatTransport(replace(self.settings, model_max_output_tokens=new_limit), transport=self.transport.transport, on_stream=self.transport.on_stream, request_state=self.transport.request_state)
                                notice = f'输出截断，自动提高至{new_limit} token重试一次。'
                        elif isinstance(error, ModelStructureError):
                            messages = [*messages, {'role': 'user', 'content': f'上一回复的校验结果：{error} 重新输出本维度完整JSON，逐项核对系统schema所有必填字段，不新增字段。check_scores必须与全部细则等长，index从1顺序排列；每项分数不超过对应checklist_scores且最多两位小数，维度score必须等于逐项精确相加的和。如任何小项为null，维度score必须为null且status=unscorable。证据仍须原样复制候选，不为凑合计修改评分依据。'}]
                            notice = '分项结构或合计不符合要求，重新生成一次。'
                        elif isinstance(error, ModelJSONError):
                            messages = [*messages, {'role': 'user', 'content': '上一回复不是单个有效JSON对象或有重复字段。请重新生成本维度完整JSON，按系统结构包含全部小项；只输出一个JSON对象，不要Markdown、重复字段或额外说明，字符串内换行请转义；证据仍须逐字复制原文。不要修补或猜测原回复中的分值。'}]
                            notice = '返回格式不符合JSON要求，重新生成一次。'
                        else:
                            messages = [*messages, {'role': 'user', 'content': '上一回复的引用未通过逐字核验。请重新生成本维度完整JSON，原文引用逐字复制evidence_candidates中的quote，保持其page与chunk_id，不要改写；仍无依据则保留缺分。'}]
                            notice = '引用未通过校验，依据原文候选重试一次。'
                        diagnostics.append(f'{dimension.name}：{notice}')
                        self.progress(f'{dimension.name} · {notice}')
                        if isinstance(error,(ModelJSONError,ModelStructureError)) and getattr(transport,'response_format',None)=='json_object':
                            transport.response_format='json_schema'
                dimensions.append(checked)
                if observations is None:
                    coverage["processed_chunk_ids"] = [chunk.id for chunk in plan.chunks]
            except ModelCallError as error:
                stopped = str(error)
                diagnostics.append(f"{dimension.name}：{stopped}")
                dimensions.append(unscored(dimension, stopped, "CALL_FAILED"))
            except AssistantError as error:
                diagnostics.append(f"{dimension.name}：{error}")
                dimensions.append(unscored(dimension, str(error), "INVALID_OUTPUT"))
        return build_result(document, rubric, mode="real",
            model={"name": self.settings.model_name, "provider": getattr(self.transport,'protocol','openai_compatible'), "service": service_label(self.settings)},
            dimensions=dimensions, coverage=coverage, course_requirements=self.course_requirements, diagnostics=diagnostics)


def create_model_client(settings: Settings, *, course_requirements="", progress=None, on_stream=None) -> ModelClient:
    if settings.mode == "mock":
        return MockModelClient(settings, course_requirements=course_requirements, progress=progress)
    if settings.mode == "real":
        return OpenAICompatibleModelClient(settings, course_requirements=course_requirements, progress=progress, on_stream=on_stream)
    raise AssistantError("不支持的分析模式，请选择 mock 或 real。")

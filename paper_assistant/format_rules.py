"""加载格式规范；配置缺失或无效时显式失败，不补造学校规则。"""

import hashlib
import json
import re
from pathlib import Path

from paper_assistant.config import PROJECT_ROOT
from paper_assistant.format_schemas import FormatRule, FormatStandard
from paper_assistant.schemas import AssistantError


STANDARDS_DIRECTORY = PROJECT_ROOT / "format_rules"
MAX_STANDARD_BYTES = 1024 * 1024


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise AssistantError(f"格式规范无效：{label}不能为空或过长。")
    return value.strip()


def _identifier(value, label: str) -> str:
    value = _text(value, label)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise AssistantError(f"格式规范无效：{label}含非法字符。")
    return value


def parse_format_standard(content: bytes) -> FormatStandard:
    if not content or len(content) > MAX_STANDARD_BYTES:
        raise AssistantError("格式规范为空或超过 1 MB，无法执行检查。")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AssistantError("格式规范包含重复 JSON 字段，无法可靠解释。")
            result[key] = value
        return result
    try:
        data = json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique_object)
        if not isinstance(data, dict) or data["schema_version"] != "1.0":
            raise AssistantError("格式规范的配置格式版本必须为 1.0。")
        if type(data["is_demo"]) is not bool:
            raise AssistantError("格式规范 is_demo 必须为布尔值。")
        raw_rules = data["rules"]
        if not isinstance(raw_rules, list) or len(raw_rules) > 50:
            raise AssistantError("格式规范 rules 须为列表，最多 50 条；空列表不会视作检查通过。")
        rules = []
        for item in raw_rules:
            method = _text(item["method"], "检查方法")
            parameters = item["parameters"]
            if not isinstance(parameters, dict):
                raise AssistantError("格式规则 parameters 须为对象。")
            if method == "section_presence":
                if set(parameters) != {"section"} or parameters["section"] not in {"摘要", "关键词", "参考文献"}:
                    raise AssistantError("节结构检出只支持 section=摘要、关键词或参考文献，不接受未实现的附加参数。")
            enabled = item.get("enabled", True)
            if type(enabled) is not bool:
                raise AssistantError("格式规则 enabled 必须为布尔值。")
            rules.append(FormatRule(
                _identifier(item["id"], "规则编号"), _text(item["name"], "规则名称"),
                _text(item["source"], "规则来源"), _text(item["version"], "规则版本"),
                _text(item["scope"], "规则适用范围"), method, _text(item["requirement"], "规则要求"), parameters, enabled,
            ))
        if len({item.id for item in rules}) != len(rules):
            raise AssistantError("格式规则编号不能重复。")
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        return FormatStandard(
            _identifier(data["id"], "规范编号"), _text(data["name"], "规范名称"),
            _text(data["version"], "规范版本"), _text(data["source"], "规范来源"),
            _text(data["scope"], "规范适用范围"), data["is_demo"], tuple(rules), hashlib.sha256(canonical).hexdigest(),
        )
    except AssistantError:
        raise
    except (UnicodeError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise AssistantError("格式规范无效：JSON 错误或缺少名称、来源、版本、适用范围、检查方法等必要字段。") from None


def load_format_standard(path: Path) -> FormatStandard:
    try:
        return parse_format_standard(path.read_bytes())
    except OSError:
        raise AssistantError("格式规范文件缺失或无法读取；未使用演示规则自动替代。") from None


def list_format_standards() -> tuple[Path, ...]:
    return tuple(sorted(STANDARDS_DIRECTORY.glob("*.json")))

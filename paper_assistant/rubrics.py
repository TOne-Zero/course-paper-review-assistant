"""从独立 JSON 加载课程评分标准，并验证维度与分值配置。"""

import json
import os
import re
import tempfile
from dataclasses import asdict, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from paper_assistant.config import PROJECT_ROOT
from paper_assistant.rubric_defaults import default_score_bands
from paper_assistant.schemas import DEFAULT_WEIGHT_NOTE, AssistantError, Rubric, RubricDimension, RubricReference, ScoreBand


LOCAL_DIRECTORY = PROJECT_ROOT / "rubrics" / "local"
MAX_CONFIG_BYTES = 1024 * 1024


def _fail(message: str) -> None:
    raise AssistantError("评分标准无效：" + message)


def _text(value, label: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(f"{label}不能为空，且不能超过 {maximum} 字符。")
    return value.strip()


def _number(value, label: str, maximum: float = 100) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label}必须是数字。")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= Decimal(str(maximum)):
            _fail(f"{label}必须是 0 至 {maximum} 之间的有限数字。")
    except (InvalidOperation, ValueError):
        _fail(f"{label}必须是有效数字。")
    return number


def parse_rubric_config(data: dict) -> Rubric:
    """唯一配置校验入口：拒绝非法分值、总分、维度和不连续分档。"""
    if not isinstance(data, dict) or data.get("schema_version") != "2.0":
        _fail("配置格式版本必须为 2.0，请使用当前导出的配置。")
    try:
        rubric_id = _text(data["id"], "标准标识", 80)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", rubric_id):
            _fail("标准标识只能包含英文字母、数字、下划线或短横线。")
        raw_references = data.get("references", [])
        if not isinstance(raw_references, list) or len(raw_references) > 30:
            _fail("参考来源须为列表，最多 30 项。")
        references = []
        for source in raw_references:
            reference_id = _text(source["id"], "参考来源标识", 80)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", reference_id):
                _fail("参考来源标识含非法字符。")
            url = _text(source["url"], "参考来源链接", 2000)
            try:
                parts = urlsplit(url)
            except ValueError:
                _fail("参考来源链接格式无效。")
            if parts.scheme not in {"https", "http"} or not parts.netloc or parts.username or parts.password:
                _fail("参考来源须使用不含账号密码的 HTTP 或 HTTPS 链接。")
            references.append(RubricReference(reference_id, _text(source["citation"], "参考文献"), url,
                                              _text(source["note"], "参考来源适用说明")))
        known_references = {source.id for source in references}
        if len(known_references) != len(references):
            _fail("参考来源标识不能重复。")
        weight_note = _text(data.get("weight_note", DEFAULT_WEIGHT_NOTE), "权重说明")
        items = data["dimensions"]
        if not isinstance(items, list) or not 1 <= len(items) <= 30:
            _fail("维度数量必须在 1 至 30 之间。")
        dimensions = []
        total = Decimal(0)
        for item in items:
            name = _text(item["name"], "维度名称", 100)
            dimension_id = _text(item["id"], f"{name}标识", 80)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", dimension_id):
                _fail("维度标识含非法字符。")
            score = _number(item["max_score"], f"{name}满分")
            if score <= 0 or score != score.quantize(Decimal("0.01")):
                _fail(f"{name}满分必须大于 0，且最多保留两位小数。")
            total += score
            checks = item["checklist"]
            if not isinstance(checks, list) or not 1 <= len(checks) <= 50:
                _fail(f"{name}至少需要一项检查内容，最多 50 项。")
            checks = tuple(_text(check, f"{name}检查内容") for check in checks)
            raw_scores = item.get('checklist_scores', [])
            if not isinstance(raw_scores, (list, tuple)):
                _fail(f"{name}细则分值须为列表。")
            check_scores = tuple(_number(value, f"{name}细则分值") for value in raw_scores)
            if check_scores and (len(check_scores) != len(checks) or sum(check_scores) != score
                                 or any(value != value.quantize(Decimal('0.01')) for value in check_scores)):
                _fail(f"{name}细则分值须逐条对应、最多两位小数，且合计等于本维度满分。")
            raw_bands = item["score_bands"]
            if not isinstance(raw_bands, list) or not 1 <= len(raw_bands) <= 10:
                _fail(f"{name}需要 1 至 10 个分档。")
            bands = []
            boundary = Decimal(0)
            labels = set()
            for raw in raw_bands:
                low = _number(raw["min_ratio"], "分档下界", 1)
                high = _number(raw["max_ratio"], "分档上界", 1)
                label = _text(raw["label"], "档位名称", 100)
                if low != boundary or high <= low or label in labels:
                    _fail(f"{name}分档须按从低到高排列、连续覆盖 0–100%，且档位名称不能重复。")
                labels.add(label)
                boundary = high
                bands.append(ScoreBand(label, float(low), float(high), _text(raw["description"], "分档描述")))
            if boundary != 1:
                _fail(f"{name}分档须完整覆盖 0–100%。")
            reference_ids = item.get("reference_ids", [])
            if (not isinstance(reference_ids, list) or not all(isinstance(value, str) for value in reference_ids)
                    or len(reference_ids) != len(set(reference_ids)) or not set(reference_ids).issubset(known_references)):
                _fail(f"{name}的参考来源标识重复或未在配置中定义。")
            required = item.get("required", True)
            if type(required) is not bool:
                _fail(f"{name}的 required 必须是布尔值。")
            dimensions.append(RubricDimension(
                dimension_id, name, float(score), _text(item["description"], f"{name}评价要求"), checks, tuple(bands),
                tuple(reference_ids),
                required,
                tuple(float(value) for value in check_scores),
            ))
        if len({item.id for item in dimensions}) != len(dimensions) or len({item.name for item in dimensions}) != len(dimensions):
            _fail("维度标识和维度名称都必须唯一。")
        if _number(data["total_score"], "总分") != 100 or total != 100:
            _fail(f"各维度满分合计必须为 100，当前为 {total}。")
        if type(data["is_demo"]) is not bool:
            _fail("is_demo 必须为布尔值。")
        return Rubric(
            rubric_id, _text(data["name"], "标准名称", 200), _text(data["version"], "配置版本", 80),
            _text(data["description"], "标准说明"), tuple(dimensions), data["is_demo"],
            weight_note=weight_note, references=tuple(references),
        )
    except (KeyError, TypeError, AttributeError):
        _fail("缺少必要字段或字段类型错误，请参照演示配置。")


def rubric_to_dict(rubric: Rubric) -> dict:
    try:
        data = asdict(rubric)
        # 转为纯 JSON 类型，便于编辑、导入与再次校验。
        data = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
        data["total_score"] = rubric.total_score
        for dimension in data['dimensions']:
            if not dimension['checklist_scores']:
                del dimension['checklist_scores']
        return data
    except (ValueError, TypeError, OverflowError):
        _fail("配置字段或分值无效，分数必须是有限数字。")


def export_rubric(rubric: Rubric) -> bytes:
    data = rubric_to_dict(rubric)
    parse_rubric_config(data)
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(content) > MAX_CONFIG_BYTES:
        _fail("配置超过 1 MB，请缩减说明和检查内容。")
    return content


def import_rubric(content: bytes) -> Rubric:
    if not content or len(content) > MAX_CONFIG_BYTES:
        _fail("配置为空或超过 1 MB。")
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                _fail("JSON 包含重复字段。")
            obj[key] = value
        return obj
    try:
        data = json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, AssistantError):
            raise
        _fail("请导入 UTF-8 编码的有效 JSON 配置。")
    return parse_rubric_config(data)


def save_rubric(rubric: Rubric, directory: Path | None = None, expected_version: str | None = None) -> Rubric:
    """只保存 local_ 开头的本地副本，不覆盖内置演示标准；原子替换文件。"""
    parse_rubric_config(rubric_to_dict(rubric))
    if not re.fullmatch(r"local_[A-Za-z0-9_-]+", rubric.id):
        _fail("请另存为本地配置，不允许覆盖内置演示标准。")
    directory = directory if directory is not None else LOCAL_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{rubric.id}.json"
    old = import_rubric(path.read_bytes()) if path.exists() else None
    if old is not None and old.version != expected_version:
        _fail("此配置已被其它页面更新，请重新加载后再保存。")
    if old is None and expected_version is not None:
        _fail("原配置已不存在，请重新加载后另存为新配置。")
    if old and not re.fullmatch(r"local-[1-9]\d*", old.version):
        _fail("本地配置版本格式无效，请导出后作为新配置重新导入。")
    revision = int(old.version.removeprefix("local-")) + 1 if old else 1
    saved = replace(rubric, version=f"local-{revision}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(export_rubric(saved))
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return saved


def load_rubrics(directory: Path | None = None) -> tuple[Rubric, ...]:
    directory = directory if directory is not None else PROJECT_ROOT / "rubrics"
    rubrics = []
    try:
        paths = sorted(directory.glob("*.json"))
        if directory == PROJECT_ROOT / "rubrics":
            paths += sorted(LOCAL_DIRECTORY.glob("*.json"))
        for path in paths:
            content = path.read_bytes()
            data = json.loads(content.decode("utf-8-sig"))
            # 兼容最初内置的两份 v1 示例；不静默接受缺字段的 v2 配置。
            if isinstance(data, dict) and "schema_version" not in data:
                data = dict(data, schema_version="2.0", total_score=100, is_demo=True)
                data["name"] = data["name"].replace("（示例）", "（演示标准）")
                for item in data["dimensions"]:
                    item["checklist"] = [item["description"]]
                    item["score_bands"] = default_score_bands(item["description"])
                rubrics.append(parse_rubric_config(data))
            else:
                rubrics.append(import_rubric(content))
        if not rubrics or len({r.id for r in rubrics}) != len(rubrics):
            raise ValueError("没有可用标准或标准 ID 重复")
    except AssistantError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise AssistantError("评分标准加载失败，请检查 rubrics/*.json 的字段、唯一 ID 和满分合计。") from None
    return tuple(rubrics)

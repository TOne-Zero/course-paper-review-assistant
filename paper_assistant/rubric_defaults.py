"""本地演示的默认分档；不来自任何高校官方标准。"""
import re
from dataclasses import replace


def equal_scores(total, count):
    cents = round(total * 100)
    each, remainder = divmod(cents, count)
    return tuple((each + (remainder if index == count - 1 else 0)) / 100 for index in range(count))


def weighted_rubric(rubric):
    dimensions = []
    for dimension in rubric.dimensions:
        if dimension.checklist_scores:
            dimensions.append(dimension)
            continue
        checks = tuple(part.strip() for text in dimension.checklist for part in re.split(r'[;；\r\n]+', text) if part.strip())
        dimensions.append(replace(dimension, checklist=checks, checklist_scores=equal_scores(dimension.max_score, len(checks))))
    return replace(rubric, dimensions=tuple(dimensions))


def demonstration_scores(maxima, ratio):
    """仅供模拟/受控测试，按分配额产生固定比例值并保留分币合计。"""
    limits = [round(value * 100) for value in maxima]
    values = [int(limit * ratio) for limit in limits]
    remainder = round(sum(limits) * ratio) - sum(values)
    for index in reversed(range(len(values))):
        addition = min(remainder, limits[index] - values[index])
        values[index] += addition
        remainder -= addition
    return [value / 100 for value in values]


def default_score_bands(goal: str) -> list[dict]:
    return [
        {"label": "有待改进", "min_ratio": 0.0, "max_ratio": 0.6,
         "description": f"未清楚交代{goal}，关键内容或支撑材料缺失。"},
        {"label": "基本达到", "min_ratio": 0.6, "max_ratio": 0.75,
         "description": f"初步交代{goal}，但完整性、依据或一致性仍需改进。"},
        {"label": "较好达到", "min_ratio": 0.75, "max_ratio": 0.9,
         "description": f"较完整地交代{goal}，依据可核对，少量不足不影响主要结论。"},
        {"label": "充分达到", "min_ratio": 0.9, "max_ratio": 1.0,
         "description": f"清晰、完整地交代{goal}，依据充分，能说明适用范围和局限。"},
    ]

"""格式检查的数据契约；机器判断与教师复核分别保存。"""

from dataclasses import dataclass
from typing import Any, Literal


FormatStatus = Literal["符合", "疑似不符合", "无法判断"]


@dataclass(frozen=True)
class FormatRule:
    id: str
    name: str
    source: str
    version: str
    scope: str
    method: str
    requirement: str
    parameters: dict[str, Any]
    enabled: bool = True


@dataclass(frozen=True)
class FormatStandard:
    id: str
    name: str
    version: str
    source: str
    scope: str
    is_demo: bool
    rules: tuple[FormatRule, ...]
    digest: str


@dataclass(frozen=True)
class FormatEvidence:
    page: int
    start_line: int
    end_line: int
    quote: str


@dataclass(frozen=True)
class FormatRuleResult:
    rule_id: str
    name: str
    status: FormatStatus
    reason: str
    rule_source: str
    rule_version: str
    rule_scope: str
    method: str
    requirement: str
    checked_pages: tuple[int, ...] = ()
    uncertain_pages: tuple[int, ...] = ()
    evidence: tuple[FormatEvidence, ...] = ()


@dataclass(frozen=True)
class FormatCheckReport:
    document_sha256: str | None
    document_name: str | None
    standard_id: str | None
    standard_name: str | None
    standard_version: str | None
    standard_digest: str | None
    is_demo: bool | None
    results: tuple[FormatRuleResult, ...]
    limitations: tuple[str, ...]
    engine_version: str = "1.0"

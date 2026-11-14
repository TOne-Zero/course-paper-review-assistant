"""班级成绩存档：SQLite 持久化、及格/不及格分组与截断正态赋分。"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import sqlite3
import threading
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePath
from uuid import uuid4

from paper_assistant.schemas import AssistantError

DEFAULT_PARAMS = {"threshold": 60.0, "pass_mean": 75.0, "pass_sd": 25.0,
                  "fail_mean": 50.0, "fail_sd": 8.0, "decimals": 1}
PARAM_KEYS = ("threshold", "pass_mean", "pass_sd", "fail_mean", "fail_sd")
SHAPES = ("balanced", "high", "low", "custom")
SHAPE_LABELS = {"balanced": "均衡", "high": "高分集中", "low": "低分集中", "custom": "自定义"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS classes(
  id TEXT PRIMARY KEY, mode TEXT NOT NULL, name TEXT NOT NULL, course TEXT NOT NULL DEFAULT '',
  threshold REAL NOT NULL, pass_mean REAL NOT NULL, pass_sd REAL NOT NULL,
  fail_mean REAL NOT NULL, fail_sd REAL NOT NULL, decimals INTEGER NOT NULL,
  shape TEXT NOT NULL DEFAULT 'balanced', intensity INTEGER NOT NULL DEFAULT 50,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, normalized_at TEXT,
  UNIQUE(mode, name));
CREATE TABLE IF NOT EXISTS batches(
  id TEXT PRIMARY KEY, class_id TEXT NOT NULL, rubric_name TEXT NOT NULL DEFAULT '',
  rubric_version TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
  FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS papers(
  id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, class_id TEXT NOT NULL, position INTEGER NOT NULL,
  name TEXT NOT NULL, title TEXT NOT NULL, raw_total REAL, adjusted_total REAL, band TEXT,
  dimensions TEXT NOT NULL DEFAULT '[]', report_md TEXT NOT NULL DEFAULT '',
  report_json TEXT NOT NULL DEFAULT '', teacher_note TEXT NOT NULL DEFAULT '',
  reviewed INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE CASCADE,
  FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_papers_class ON papers(class_id);
CREATE INDEX IF NOT EXISTS idx_batches_class ON batches(class_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normal_cdf(value: float) -> float:
    return 0.5 * math.erfc(-value / math.sqrt(2.0))


def _round(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return math.floor(value * factor + 0.5) / factor


def _truncated_quantile(percent: float, mean: float, sd: float, low: float, high: float) -> float:
    """截断正态分布中累计概率为 percent 的分位点；二分求解，保证落在区间内。"""
    if high <= low:
        return low
    a, b = (low - mean) / sd, (high - mean) / sd
    start, end = _normal_cdf(a), _normal_cdf(b)
    target = start + min(max(percent, 0.0), 1.0) * (end - start)
    left, right = low, high
    for _ in range(80):
        middle = (left + right) / 2
        if _normal_cdf((middle - mean) / sd) < target:
            left = middle
        else:
            right = middle
        if right - left < 1e-9:
            break
    return (left + right) / 2


def assign_scores(papers: list[dict], params: dict) -> dict[str, tuple[str | None, float | None]]:
    """按原始总分分组，组内排名百分位映射到截断正态分布；同分同分，保持组内顺序。"""
    threshold, decimals = params["threshold"], int(params["decimals"])
    edge = 10 ** -decimals
    plan = [("pass", params["pass_mean"], params["pass_sd"], threshold, 100.0, False),
            ("fail", params["fail_mean"], params["fail_sd"], 0.0, threshold, True)]
    result: dict[str, tuple[str | None, float | None]] = {}
    for band, mean, sd, low, high, exclusive_high in plan:
        group = sorted((p for p in papers if p.get("raw_total") is not None
                        and (p["raw_total"] >= threshold if band == "pass" else p["raw_total"] < threshold)),
                       key=lambda item: (item["raw_total"], item["position"]))
        size = len(group)
        index = 0
        while index < size:
            end = index
            while end + 1 < size and group[end + 1]["raw_total"] == group[index]["raw_total"]:
                end += 1
            midrank = ((index + 1) + (end + 1)) / 2
            score = _truncated_quantile((midrank - 0.5) / size, mean, sd, low, high)
            score = _round(score, decimals)
            upper = high - edge if exclusive_high else high
            score = min(upper, max(low, score))
            score = _round(score, decimals)
            for offset in range(index, end + 1):
                result[group[offset]["id"]] = (band, score)
            index = end + 1
    return result


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sd(values: list[float]) -> float | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _bins(values: list[float]) -> list[int]:
    return [sum(1 for v in values if v < 60), sum(1 for v in values if 60 <= v < 70),
            sum(1 for v in values if 70 <= v < 80), sum(1 for v in values if 80 <= v < 90),
            sum(1 for v in values if v >= 90)]


def _stats(papers: list[dict]) -> dict:
    raw = [p["rawTotal"] for p in papers if p.get("rawTotal") is not None]
    adjusted = [p["adjustedTotal"] for p in papers if p.get("adjustedTotal") is not None]
    passed = sum(1 for p in papers if p.get("band") == "pass")
    return {"rawMean": _mean(raw), "rawSd": _sd(raw), "adjustedMean": _mean(adjusted),
            "adjustedSd": _sd(adjusted), "passRate": (passed / len(raw) * 100) if raw else None,
            "rawBins": _bins(raw), "adjustedBins": _bins(adjusted)}


def _number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AssistantError(f"{label}必须是有效数字。")
    return float(value)


def _preset_params(shape: str, intensity: int) -> dict:
    """均衡参数向目标形态按强度插值；只调整对应分组。"""
    pass_mean, pass_sd, fail_mean, fail_sd = 75.0, 25.0, 50.0, 8.0
    if shape == "high":
        factor = intensity / 100
        pass_mean += factor * (100.0 - pass_mean)
        pass_sd += factor * (4.0 - pass_sd)
    elif shape == "low":
        factor = intensity / 100
        fail_mean += factor * (40.0 - fail_mean)
        fail_sd += factor * (4.0 - fail_sd)
    return {"pass_mean": round(pass_mean, 2), "pass_sd": round(pass_sd, 2),
            "fail_mean": round(fail_mean, 2), "fail_sd": round(fail_sd, 2)}


def _validate_params(payload) -> dict:
    source = payload if isinstance(payload, dict) else {}
    shape = source.get("shape", "custom")
    if shape not in SHAPES:
        raise AssistantError("赋分形态无效。")
    intensity = source.get("intensity", 50)
    if (isinstance(intensity, bool) or not isinstance(intensity, (int, float)) or not math.isfinite(intensity)
            or not 0 <= intensity <= 100 or float(intensity) % 5):
        raise AssistantError("集中强度须为0至100之间、步长5的整数。")
    intensity = int(intensity)
    threshold = _number(source.get("threshold", DEFAULT_PARAMS["threshold"]), "及格线")
    decimals = source.get("decimals", DEFAULT_PARAMS["decimals"])
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 2:
        raise AssistantError("保留小数位仅支持0至2位。")
    if shape in ("balanced", "high", "low"):
        groups = _preset_params(shape, intensity)
    else:
        groups = {}
        for key, camel, label in (("pass_mean", "passMean", "及格组均值"), ("pass_sd", "passSd", "及格组标准差"),
                                  ("fail_mean", "failMean", "不及格组均值"), ("fail_sd", "failSd", "不及格组标准差")):
            value = source[key] if key in source else source.get(camel, DEFAULT_PARAMS[key])
            groups[key] = _number(value, label)
    if not 0 <= threshold <= 100:
        raise AssistantError("及格线必须在0至100之间。")
    if not 0 < groups["pass_sd"] <= 30 or not 0 < groups["fail_sd"] <= 30:
        raise AssistantError("标准差必须大于0且不超过30。")
    if not 0 <= groups["pass_mean"] <= 100 or not 0 <= groups["fail_mean"] <= 100:
        raise AssistantError("组均值必须在0至100之间。")
    return {"threshold": threshold, **groups, "decimals": decimals, "shape": shape, "intensity": intensity}


def _param_view(row) -> dict:
    return {"threshold": row["threshold"], "passMean": row["pass_mean"], "passSd": row["pass_sd"],
            "failMean": row["fail_mean"], "failSd": row["fail_sd"], "decimals": row["decimals"],
            "shape": row["shape"], "intensity": row["intensity"]}


def _summary(row) -> dict:
    count = row["paper_count"] or 0
    scored = row["scored_count"] or 0
    passed = row["pass_count"] or 0
    return {"id": row["id"], "name": row["name"], "course": row["course"], "paperCount": count,
            "scoredCount": scored, "passCount": passed, "failCount": (row["fail_count"] or 0),
            "rawMean": row["raw_mean"] if scored else None,
            "adjustedMean": row["adjusted_mean"] if scored else None,
            "passRate": (passed / scored * 100) if scored else None,
            "threshold": row["threshold"], "normalizedAt": row["normalized_at"],
            "lastArchivedAt": row["last_at"]}


SUMMARY_SQL = """
SELECT c.id, c.name, c.course, c.threshold, c.pass_mean, c.pass_sd, c.fail_mean, c.fail_sd, c.decimals,
  c.shape, c.intensity, c.normalized_at,
  (SELECT COUNT(*) FROM papers p WHERE p.class_id = c.id) AS paper_count,
  (SELECT COUNT(*) FROM papers p WHERE p.class_id = c.id AND p.raw_total IS NOT NULL) AS scored_count,
  (SELECT COUNT(*) FROM papers p WHERE p.class_id = c.id AND p.band = 'pass') AS pass_count,
  (SELECT COUNT(*) FROM papers p WHERE p.class_id = c.id AND p.band = 'fail') AS fail_count,
  (SELECT AVG(p.raw_total) FROM papers p WHERE p.class_id = c.id AND p.raw_total IS NOT NULL) AS raw_mean,
  (SELECT AVG(p.adjusted_total) FROM papers p WHERE p.class_id = c.id AND p.adjusted_total IS NOT NULL) AS adjusted_mean,
  (SELECT MAX(b.created_at) FROM batches b WHERE b.class_id = c.id) AS last_at
FROM classes c WHERE c.mode = ?
"""


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(classes)")}
            if "shape" not in columns:
                connection.execute("ALTER TABLE classes ADD COLUMN shape TEXT NOT NULL DEFAULT 'balanced'")
            if "intensity" not in columns:
                connection.execute("ALTER TABLE classes ADD COLUMN intensity INTEGER NOT NULL DEFAULT 50")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def payload(self, mode: str) -> dict:
        with self.lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(SUMMARY_SQL + " ORDER BY last_at DESC", (mode,)).fetchall()
            return {"classes": [_summary(row) for row in rows],
                    "defaults": {"threshold": DEFAULT_PARAMS["threshold"], "passMean": DEFAULT_PARAMS["pass_mean"],
                                 "passSd": DEFAULT_PARAMS["pass_sd"], "failMean": DEFAULT_PARAMS["fail_mean"],
                                 "failSd": DEFAULT_PARAMS["fail_sd"], "decimals": DEFAULT_PARAMS["decimals"],
                                 "shape": "balanced", "intensity": 50},
                    "notice": "成绩仅保存在本机 SQLite；AI初评与教师复核记录随报告一并归档。"}

    def _class(self, connection, mode: str, class_id: str):
        row = connection.execute(SUMMARY_SQL + " AND c.id = ?", (mode, class_id)).fetchone()
        if row is None:
            raise AssistantError("班级存档不存在，可能已被删除。")
        return row

    def create_batch(self, mode: str, payload: dict, papers: list[dict]) -> dict:
        name = (payload.get("className") or "").strip() if isinstance(payload.get("className"), str) else ""
        course = (payload.get("course") or "").strip() if isinstance(payload.get("course"), str) else ""
        if not 1 <= len(name) <= 40:
            raise AssistantError("班级名称须为1–40个字符。")
        if len(course) > 60:
            raise AssistantError("课程名称最多60个字符。")
        if not papers:
            raise AssistantError("没有可归档的完整评分。")
        params = _validate_params({**DEFAULT_PARAMS, "shape": "balanced", "intensity": 50, **payload})
        now = _now()
        with self.lock, closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT * FROM classes WHERE mode = ? AND name = ?", (mode, name)).fetchone()
            if row:
                class_id = row["id"]
                if course and not row["course"]:
                    connection.execute("UPDATE classes SET course = ? WHERE id = ?", (course, class_id))
            else:
                class_id = uuid4().hex
                connection.execute("INSERT INTO classes(id, mode, name, course, threshold, pass_mean, pass_sd, fail_mean, fail_sd, decimals, shape, intensity, created_at, updated_at) "
                                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (class_id, mode, name, course, params["threshold"], params["pass_mean"], params["pass_sd"],
                                    params["fail_mean"], params["fail_sd"], params["decimals"], params["shape"], params["intensity"], now, now))
            batch_id = uuid4().hex
            connection.execute("INSERT INTO batches(id, class_id, rubric_name, rubric_version, created_at) VALUES (?,?,?,?,?)",
                               (batch_id, class_id, str(payload.get("rubricName") or "")[:80],
                                str(payload.get("rubricVersion") or "")[:80], now))
            for position, paper in enumerate(papers, 1):
                connection.execute("INSERT INTO papers(id, batch_id, class_id, position, name, title, raw_total, dimensions, report_md, report_json, teacher_note, reviewed) "
                                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (uuid4().hex, batch_id, class_id, position, paper["name"][:200], paper["title"][:200],
                                    paper["raw_total"], json.dumps(paper.get("dimensions", []), ensure_ascii=False),
                                    paper.get("report_md", ""), paper.get("report_json", ""),
                                    paper.get("teacher_note", ""), 1 if paper.get("reviewed") else 0))
            connection.execute("UPDATE classes SET updated_at = ? WHERE id = ?", (now, class_id))
            self._renormalize(connection, class_id)
            return {"classId": class_id, "className": name, "archived": len(papers)}

    def detail(self, mode: str, class_id: str) -> dict:
        with self.lock, closing(self._connect()) as connection, connection:
            row = self._class(connection, mode, class_id)
            papers = connection.execute("SELECT p.* FROM papers p JOIN batches b ON b.id = p.batch_id "
                                        "WHERE p.class_id = ? ORDER BY b.created_at, p.position", (class_id,)).fetchall()
            batches = connection.execute("SELECT * FROM batches WHERE class_id = ? ORDER BY created_at DESC", (class_id,)).fetchall()
            items = [{"id": paper["id"], "batchId": paper["batch_id"], "name": paper["name"], "title": paper["title"],
                      "rawTotal": paper["raw_total"], "adjustedTotal": paper["adjusted_total"], "band": paper["band"],
                      "reviewed": bool(paper["reviewed"]), "teacherNote": paper["teacher_note"],
                      "dimensions": json.loads(paper["dimensions"] or "[]")} for paper in papers]
            batch_items = [{"id": batch["id"], "createdAt": batch["created_at"], "rubricName": batch["rubric_name"],
                            "rubricVersion": batch["rubric_version"],
                            "paperCount": sum(1 for item in items if item["batchId"] == batch["id"])} for batch in batches]
            return {"class": {**_summary(row), **_param_view(row)}, "papers": items, "batches": batch_items,
                    "stats": _stats(items)}

    def normalize(self, mode: str, class_id: str, payload: dict) -> dict:
        params = _validate_params(payload)
        with self.lock, closing(self._connect()) as connection, connection:
            self._class(connection, mode, class_id)
            connection.execute("UPDATE classes SET threshold=?, pass_mean=?, pass_sd=?, fail_mean=?, fail_sd=?, decimals=?, shape=?, intensity=?, updated_at=? WHERE id=?",
                               (params["threshold"], params["pass_mean"], params["pass_sd"], params["fail_mean"],
                                params["fail_sd"], params["decimals"], params["shape"], params["intensity"], _now(), class_id))
            self._renormalize(connection, class_id)
        return self.detail(mode, class_id)

    def _renormalize(self, connection, class_id: str) -> None:
        row = connection.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
        papers = [dict(paper) for paper in connection.execute("SELECT id, raw_total, position FROM papers WHERE class_id = ?", (class_id,)).fetchall()]
        scores = assign_scores(papers, {"threshold": row["threshold"], "pass_mean": row["pass_mean"], "pass_sd": row["pass_sd"],
                                        "fail_mean": row["fail_mean"], "fail_sd": row["fail_sd"], "decimals": row["decimals"]})
        for paper in papers:
            band, score = scores.get(paper["id"], (None, None))
            connection.execute("UPDATE papers SET band = ?, adjusted_total = ? WHERE id = ?", (band, score, paper["id"]))
        connection.execute("UPDATE classes SET normalized_at = ? WHERE id = ?", (_now(), class_id))

    def delete_class(self, mode: str, class_id: str) -> None:
        with self.lock, closing(self._connect()) as connection, connection:
            row = self._class(connection, mode, class_id)
            connection.execute("DELETE FROM classes WHERE id = ?", (row["id"],))

    def delete_batch(self, mode: str, batch_id: str) -> None:
        with self.lock, closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT b.*, c.mode AS class_mode FROM batches b JOIN classes c ON c.id = b.class_id WHERE b.id = ?",
                                     (batch_id,)).fetchone()
            if row is None or row["class_mode"] != mode:
                raise AssistantError("存档批次不存在，可能已被删除。")
            connection.execute("DELETE FROM batches WHERE id = ?", (row["id"],))
            self._renormalize(connection, row["class_id"])
            connection.execute("UPDATE classes SET updated_at = ? WHERE id = ?", (_now(), row["class_id"]))

    def export_class(self, mode: str, class_id: str) -> bytes:
        with self.lock, closing(self._connect()) as connection, connection:
            row = self._class(connection, mode, class_id)
            papers = connection.execute("SELECT p.* FROM papers p JOIN batches b ON b.id = p.batch_id "
                                        "WHERE p.class_id = ? ORDER BY b.created_at, p.position", (class_id,)).fetchall()
            if not papers:
                raise AssistantError("这个班级还没有可导出的成绩。")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            scores = io.StringIO()
            writer = csv.writer(scores)
            writer.writerow(["序号", "文件", "标题", "原始总分", "分组", "正态赋分", "教师复核", "教师备注"])
            for index, paper in enumerate(papers, 1):
                stem = PurePath(paper["name"].replace("\\", "/")).stem
                safe = re.sub(r'[^\w\u4e00-\u9fff .-]', "_", stem).strip(" .")[:70] or "论文"
                prefix = f"{index:02d}_{safe}"
                if paper["report_md"]:
                    archive.writestr(prefix + ".md", paper["report_md"])
                if paper["report_json"]:
                    archive.writestr(prefix + ".json", paper["report_json"])
                band = {"pass": "及格组", "fail": "不及格组"}.get(paper["band"], "未评分")
                writer.writerow([index, paper["name"], paper["title"],
                                 "" if paper["raw_total"] is None else f'{paper["raw_total"]:.2f}',
                                 band, "" if paper["adjusted_total"] is None else f'{paper["adjusted_total"]:.2f}',
                                 "已确认" if paper["reviewed"] else "未确认", paper["teacher_note"]])
            archive.writestr("班级成绩单.csv", scores.getvalue().encode("utf-8-sig"))
            archive.writestr("存档说明.json", json.dumps({
                "班级": row["name"], "课程": row["course"], "及格线": row["threshold"],
                "赋分形态": SHAPE_LABELS.get(row["shape"], row["shape"]),
                "集中强度": f'{row["intensity"]}%',
                "及格组均值": row["pass_mean"], "及格组标准差": row["pass_sd"],
                "不及格组均值": row["fail_mean"], "不及格组标准差": row["fail_sd"],
                "保留小数位": row["decimals"], "说明": "组内按原始总分排名映射到截断正态分布；集中形态仅调整对应分组；AI辅助评价，最终成绩由教师确定。"},
                ensure_ascii=False, indent=2).encode("utf-8"))
        return output.getvalue()

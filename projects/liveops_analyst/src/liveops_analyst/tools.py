"""Dictionary and aggregate slices only. No player-level rows, no config writer."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class MetricStore:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding="utf-8"))

    def read(self, metric_id: str) -> dict | None:
        row = self.rows.get(metric_id)
        if not row:
            return None
        return {"id": metric_id, **row}


class SliceStore:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding="utf-8"))

    def read(self, event_id: str) -> dict | None:
        row = self.rows.get(event_id)
        return dict(row) if row else None


def load_stores(data_dir: Path | None = None):
    root = data_dir or DATA_DIR
    return MetricStore(root / "metrics.json"), SliceStore(root / "slices.json")


def find_confounders(slices: dict) -> tuple[list[dict], dict]:
    base = slices["baseline"]
    current = slices["event_window"]
    confounders = []
    if float(current["crash_rate"]) - float(base["crash_rate"]) >= 0.01:
        confounders.append(
            {
                "factor": "client_crash",
                "note": "崩溃率上升与次留下降同向，不能把次留变化直接归因于活动",
            }
        )
    if current.get("holiday") or base.get("holiday"):
        confounders.append({"factor": "calendar", "note": "窗口含节假日"})
    baseline = float(base["d1_retention"])
    event = float(current["d1_retention"])
    relative = (baseline - event) / baseline if baseline else None
    computed = {
        "d1_retention_baseline": baseline,
        "d1_retention_event": event,
        "d1_retention_relative_drop": relative,
        "crash_rate_baseline": float(base["crash_rate"]),
        "crash_rate_event": float(current["crash_rate"]),
        "fictional": True,
    }
    return confounders, computed

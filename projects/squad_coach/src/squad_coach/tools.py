"""Read-only match summaries. The coach cannot grant items or change rank."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class TelemetryStore:
    def __init__(self, path: Path):
        rows = json.loads(path.read_text(encoding="utf-8"))
        self.by_id = {row["match_id"]: row for row in rows}

    def read(self, match_id: str) -> dict | None:
        row = self.by_id.get(match_id)
        return dict(row) if row else None


def load_telemetry(data_dir: Path | None = None) -> TelemetryStore:
    root = data_dir or DATA_DIR
    return TelemetryStore(root / "telemetry.json")


def derive_mistakes(telemetry: dict) -> list[dict]:
    mistakes = []
    if int(telemetry.get("unused_smokes") or 0) >= 2:
        mistakes.append({"id": "utility", "detail": "烟雾未用", "severity": 3})
    if telemetry.get("death_cause") == "third_party":
        mistakes.append({"id": "rotate", "detail": "交战过久被第三方收割", "severity": 4})
    if telemetry.get("overpeek"):
        mistakes.append({"id": "peek", "detail": "无掩体探头", "severity": 3})
    return mistakes

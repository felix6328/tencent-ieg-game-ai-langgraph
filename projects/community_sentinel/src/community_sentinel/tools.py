"""Allowlisted reads. Punishment tools are intentionally absent."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class FaqStore:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding="utf-8"))

    def search(self, text: str) -> list[dict]:
        hits = []
        for row in self.rows:
            if any(token and token in text for token in ("补给", "怎么领", "充值")):
                if "补给" in text and "补给" in row["q"]:
                    hits.append(row)
        return hits


class PlayerStore:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding="utf-8"))

    def read(self, player_id: str) -> dict:
        raw = self.rows.get(player_id) or {}
        return {
            "player_id": player_id,
            "rank": raw.get("rank", ""),
            "tenure_days": int(raw.get("tenure_days") or 0),
            "minor_account": bool(raw.get("minor_account")),
        }


class PolicyStore:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding="utf-8"))

    def ids(self) -> list[str]:
        return [row["id"] for row in self.rows]


def load_stores(data_dir: Path | None = None):
    root = data_dir or DATA_DIR
    return FaqStore(root / "faq.json"), PlayerStore(root / "players.json"), PolicyStore(root / "policies.json")

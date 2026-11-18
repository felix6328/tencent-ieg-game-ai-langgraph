"""Read-only lore plus a memory store. Canon files are never written."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class MemoryStore:
    def __init__(self, path: Path):
        self.rows = json.loads(path.read_text(encoding="utf-8"))
        self.writes: list[dict] = []

    def search(self, player_id: str, npc_id: str, limit: int = 4) -> list[dict]:
        rows = [
            row
            for row in list(self.rows) + self.writes
            if row.get("player_id") == player_id and row.get("npc_id") == npc_id
        ]
        return rows[-limit:]

    def write(self, row: dict) -> dict:
        self.writes.append(row)
        return row


class LoreStore:
    def __init__(self, path: Path):
        self.by_npc = json.loads(path.read_text(encoding="utf-8"))

    def read(self, npc_id: str) -> list[dict]:
        return list(self.by_npc.get(npc_id) or [])


def load_stores(data_dir: Path | None = None) -> tuple[MemoryStore, LoreStore]:
    root = data_dir or DATA_DIR
    return MemoryStore(root / "memories.json"), LoreStore(root / "lore.json")

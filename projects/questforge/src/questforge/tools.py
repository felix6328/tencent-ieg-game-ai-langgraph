"""Read-only canon lookup. Nothing in this package publishes to a live build."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class CanonStore:
    def __init__(self, path: Path):
        self.by_npc = json.loads(path.read_text(encoding="utf-8"))

    def read(self, npc_ids: list[str]) -> list[dict]:
        rows = []
        for npc_id in npc_ids:
            for item in self.by_npc.get(npc_id) or []:
                rows.append({"npc_id": npc_id, **item})
        return rows


def load_canon(data_dir: Path | None = None) -> CanonStore:
    root = data_dir or DATA_DIR
    return CanonStore(root / "canon.json")


def package_text(package: dict | None) -> str:
    package = package or {}
    objectives = "；".join(package.get("objectives") or [])
    return "\n".join(
        [
            package.get("title") or "",
            objectives,
            package.get("dialogue") or "",
            package.get("level_text") or "",
        ]
    )

"""Append-only audit records. Callers must pass redacted details only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def actor_hash(player_id: str) -> str:
    if not player_id:
        return ""
    return hashlib.sha256(player_id.encode("utf-8")).hexdigest()[:12]


def audit_record(node: str, decision: str, *, player_id: str = "", detail: dict | None = None, budget: dict | None = None) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "node": node,
        "decision": decision,
        "actor": actor_hash(player_id),
        "detail": detail or {},
        "tokens_used": int((budget or {}).get("tokens_used") or 0),
    }


class AuditSink:
    def __init__(self, directory: str):
        self.directory = Path(directory)

    def write(self, thread_id: str, records: list[dict]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        safe_thread = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in thread_id) or "thread"
        path = self.directory / f"{safe_thread}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

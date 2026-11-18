"""In-process per-actor rate limit. Production would use a shared store."""

from __future__ import annotations

import time


class RateLimiter:
    def __init__(self, per_min: int):
        self.per_min = per_min
        self.hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = [stamp for stamp in self.hits.get(key, []) if now - stamp < 60]
        if len(window) >= self.per_min:
            self.hits[key] = window
            return False
        window.append(now)
        self.hits[key] = window
        return True

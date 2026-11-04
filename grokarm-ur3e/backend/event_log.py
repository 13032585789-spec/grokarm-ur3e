"""Append-only JSONL log. Metrics and judge answers come from this file."""
from __future__ import annotations

import json
import time
from pathlib import Path


class EventLog:
    def __init__(self, directory: str | Path = "runs"):
        self.path = None
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.path = Path(directory) / time.strftime("session-%Y%m%d-%H%M%S.jsonl")

    def write(self, event: str, **fields) -> dict:
        record = {"ts": time.time(), "event": event, **fields}
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

"""Ghi sự kiện ra JSONL, xoay file theo giờ, fsync định kỳ (mất điện chỉ mất vài giây cuối)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import resolve


class JsonlWriter:
    def __init__(self, root: str, channel: str, session_hint: str, fsync_every_s: float = 30.0):
        self.root, self.channel, self.session_hint = resolve(root), channel, session_hint
        self.fsync_every_s = fsync_every_s
        self._f = None
        self._hour = None
        self._last_sync = time.time()
        self.n_written = 0

    def _path(self, now: datetime) -> Path:
        d = self.root / now.strftime("%Y-%m-%d") / self.channel
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.session_hint}_{now.strftime('%H')}.jsonl"

    def write(self, rec: dict) -> None:
        now = datetime.now(timezone.utc)
        if self._hour != now.strftime("%Y%m%d%H"):
            self.close()
            self._f = open(self._path(now), "a", encoding="utf-8", buffering=1)
            self._hour = now.strftime("%Y%m%d%H")
        self._f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.n_written += 1
        if time.time() - self._last_sync > self.fsync_every_s:
            self._f.flush()
            os.fsync(self._f.fileno())
            self._last_sync = time.time()

    def close(self) -> None:
        if self._f:
            self._f.flush()
            os.fsync(self._f.fileno())
            self._f.close()
            self._f = None

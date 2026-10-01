"""Ghi sự kiện ra JSONL, xoay file theo giờ, fsync định kỳ (mất điện chỉ mất vài giây cuối).

An toàn khi mất điện đột ngột:
- Mỗi dòng ghi xong là xuống OS ngay (line buffering); fsync tối đa mỗi fsync_every_s giây (mặc định 2 s)
  và fsync cả thư mục khi tạo file mới (để mục file không bị mất).
- Dòng cuối có thể bị cắt dở: data/ingest.py bỏ qua dòng JSON hỏng.
- File trạng thái nhỏ (_heartbeat.json, _quota.json) ghi bằng atomic_write_text: ghi file tạm, fsync, rồi
  os.replace -> sau sự cố luôn còn bản cũ hoặc bản mới nguyên vẹn, không bao giờ là file rỗng/cắt dở.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import resolve


def fsync_dir(d: Path) -> None:
    """fsync thư mục để mục file mới/đổi tên bền vững (bỏ qua nếu hệ điều hành không hỗ trợ)."""
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path: str | Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


class JsonlWriter:
    def __init__(self, root: str, channel: str, session_hint: str, fsync_every_s: float = 2.0):
        self.root, self.channel, self.session_hint = resolve(root), channel, session_hint
        self.fsync_every_s = fsync_every_s
        self._f = None
        self._hour = None
        self._last_sync = time.time()
        self.n_written = 0

    def _path(self, now: datetime) -> Path:
        d = self.root / now.strftime("%Y-%m-%d") / self.channel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            fsync_dir(d.parent)
        return d / f"{self.session_hint}_{now.strftime('%H')}.jsonl"

    def write(self, rec: dict) -> None:
        now = datetime.now(timezone.utc)
        if self._hour != now.strftime("%Y%m%d%H"):
            self.close()
            p = self._path(now)
            self._f = open(p, "a", encoding="utf-8", buffering=1)
            fsync_dir(p.parent)
            self._hour = now.strftime("%Y%m%d%H")
        self._f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.n_written += 1
        if time.time() - self._last_sync >= self.fsync_every_s:
            self.sync()

    def sync(self) -> None:
        if self._f:
            self._f.flush()
            os.fsync(self._f.fileno())
        self._last_sync = time.time()

    def close(self) -> None:
        if self._f:
            self.sync()
            self._f.close()
            self._f = None

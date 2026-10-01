"""Theo dõi nhiều kênh, tự bắt đầu ghi khi kênh lên sóng, giới hạn số kết nối đồng thời.

- was_offline_before=True chỉ khi scheduler đã THẤY kênh offline rồi mới live -> phiên được ghi từ đầu
  (sai số tối đa = chu kỳ poll). Đây là căn cứ cho tiêu chí "captured_from_start".
- Ghi nhịp tim ra data/raw/_heartbeat.json mỗi phút: nếu file cũ quá 5 phút là máy/WSL đã ngủ.
- Hạn mức max_sessions_per_day phiên MỚI mỗi ngày (giờ VN), lưu ở data/raw/_quota.json để không bị đặt lại khi
  service khởi động lại. Phiên không nối được lần nào thì hoàn lại hạn mức. Hết hạn mức vẫn tiếp tục poll
  (để biết kênh offline -> phiên hôm sau mới tính được captured_from_start), chỉ không mở phiên mới.
- Mọi lần mở kết nối (phiên mới và nối lại) đi qua một StartLimiter chung: cách nhau >= start_spacing_seconds
  (+ ngẫu nhiên tới start_jitter_seconds) để tránh rate limit.

Chạy: python -m livesp.capture.scheduler --config configs/capture.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import load_dotenv, load_yaml, resolve
from .recorder import ChannelRecorder, StartLimiter, check_live, configure_sign_key

log = logging.getLogger("livesp.scheduler")
VN_TZ = timezone(timedelta(hours=7))


def read_channels(path: str) -> list[dict]:
    with open(resolve(path), encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if str(r.get("enabled", "1")).strip() in ("1", "true", "True")]


class DailyQuota:
    """Đếm phiên mới theo ngày giờ VN; limit=None là không giới hạn. Trạng thái lưu ra file JSON."""

    def __init__(self, limit: int | None, path: Path | None = None, now=lambda: datetime.now(timezone.utc)):
        self.limit, self.path, self.now = limit, path, now
        self.day, self.count = self._today(), 0
        if path is not None and path.exists():
            try:
                st = json.loads(path.read_text(encoding="utf-8"))
                if st.get("date") == self.day:
                    self.count = int(st.get("count", 0))
            except (OSError, ValueError):
                pass

    def _today(self) -> str:
        return self.now().astimezone(VN_TZ).strftime("%Y-%m-%d")

    def _roll(self) -> None:
        if self._today() != self.day:
            self.day, self.count = self._today(), 0

    def _save(self) -> None:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"date": self.day, "count": self.count, "limit": self.limit}),
                                 encoding="utf-8")

    def remaining(self) -> int | None:
        self._roll()
        return None if self.limit is None else max(self.limit - self.count, 0)

    def try_take(self) -> bool:
        self._roll()
        if self.limit is not None and self.count >= self.limit:
            return False
        self.count += 1
        self._save()
        return True

    def refund(self) -> None:
        self._roll()
        self.count = max(self.count - 1, 0)
        self._save()


class Scheduler:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sem = asyncio.Semaphore(cfg.get("max_concurrent", 8))
        self.active: dict[str, float] = {}
        self.seen_offline: dict[str, bool] = {}
        raw = resolve(cfg.get("raw_dir", "data/raw"))
        self.quota = DailyQuota(cfg.get("max_sessions_per_day"), raw / "_quota.json")
        self.limiter = StartLimiter(cfg.get("start_spacing_seconds", 30), cfg.get("start_jitter_seconds", 10))
        self._quota_logged_day: str | None = None

    async def _check(self, ch: str) -> bool | None:
        return await check_live(ch)

    async def _record(self, ch: str) -> None:
        """Một phiên: lấy hạn mức, ghi, hoàn hạn mức nếu chưa nối được lần nào."""
        if not self.quota.try_take():
            if self._quota_logged_day != self.quota.day:
                log.info("Đã đủ %s phiên hôm nay; chỉ theo dõi, không mở phiên mới", self.quota.limit)
                self._quota_logged_day = self.quota.day
            return
        async with self.sem:
            self.active[ch] = time.time()
            from_start = self.seen_offline.get(ch, False)
            log.info("BẮT ĐẦU ghi %s (từ đầu phiên: %s, còn %s phiên hôm nay)", ch, from_start, self.quota.remaining())
            rec = None
            try:
                rec = ChannelRecorder(ch, self.cfg, from_start, start_limiter=self.limiter)
                await rec.record()
            except Exception as e:  # noqa: BLE001
                log.exception("recorder %s lỗi: %s", ch, e)
            finally:
                if rec is None or rec.n_connects == 0:
                    self.quota.refund()
                self.active.pop(ch, None)
                self.seen_offline[ch] = False
                log.info("KẾT THÚC ghi %s", ch)

    async def watch(self, ch: str) -> None:
        poll = self.cfg.get("poll_seconds", 120)
        await asyncio.sleep(random.uniform(0, poll))  # rải đều thời điểm kiểm tra
        err_backoff = poll
        while True:
            live = await self._check(ch)
            if live is None:
                await asyncio.sleep(err_backoff)
                err_backoff = min(err_backoff * 2, 1800)
                continue
            err_backoff = poll
            if not live:
                self.seen_offline[ch] = True
            elif ch not in self.active:
                if self.sem.locked():
                    log.warning("Hết slot, bỏ lượt %s (tăng max_concurrent nếu máy chịu được)", ch)
                else:
                    await self._record(ch)
            await asyncio.sleep(poll + random.uniform(0, 15))

    async def heartbeat(self) -> None:
        p = resolve(self.cfg.get("raw_dir", "data/raw")) / "_heartbeat.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        while True:
            p.write_text(json.dumps({"ts": time.time(), "active": list(self.active),
                                     "sessions_today": self.quota.count, "quota": self.quota.limit},
                                    ensure_ascii=False))
            await asyncio.sleep(60)

    async def run(self, channels: list[str]) -> None:
        await asyncio.gather(self.heartbeat(), *(self.watch(c) for c in channels))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/capture.yaml")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_dotenv()
    configure_sign_key()
    cfg = load_yaml(a.config)
    chans = [r["channel"].strip().lstrip("@") for r in read_channels(cfg["channels_csv"])]
    log.info("Theo dõi %d kênh, tối đa %d kết nối đồng thời, %s phiên/ngày, giãn cách %ss",
             len(chans), cfg.get("max_concurrent", 8), cfg.get("max_sessions_per_day", "∞"),
             cfg.get("start_spacing_seconds", 30))
    asyncio.run(Scheduler(cfg).run(chans))


if __name__ == "__main__":
    main()

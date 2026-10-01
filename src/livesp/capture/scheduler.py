"""Theo dõi nhiều kênh, tự bắt đầu ghi khi kênh lên sóng, giới hạn số kết nối đồng thời.

- was_offline_before=True chỉ khi scheduler đã THẤY kênh offline rồi mới live -> phiên được ghi từ đầu
  (sai số tối đa = chu kỳ poll). Đây là căn cứ cho tiêu chí "captured_from_start".
- Ghi nhịp tim ra data/raw/_heartbeat.json mỗi phút: nếu file cũ quá 5 phút là máy/WSL đã ngủ.
- Hạn mức max_sessions_per_day phiên MỚI mỗi ngày (giờ VN), lưu ở data/raw/_quota.json để không bị đặt lại khi
  service khởi động lại. Phiên không nối được lần nào thì hoàn lại hạn mức. Hết hạn mức vẫn tiếp tục poll
  (để biết kênh offline -> phiên hôm sau mới tính được captured_from_start), chỉ không mở phiên mới.
- Mọi lần mở kết nối (phiên mới và nối lại) đi qua một StartLimiter chung: cách nhau >= start_spacing_seconds
  (+ ngẫu nhiên tới start_jitter_seconds) để tránh rate limit.
- only_from_start: chỉ mở phiên khi đã THẤY kênh offline trước đó (phiên ghi từ đầu, đủ điều kiện hợp lệ).
  Kênh đang live dở lúc scheduler khởi động (sau restart/mất điện) bị bỏ qua, không tốn hạn mức.
- Tự đọc lại channels.csv mỗi channels_reload_seconds: kênh mới được theo dõi ngay; kênh bị bỏ (hoặc enabled=0)
  thôi theo dõi sau khi phiên đang ghi kết thúc tự nhiên. Không cần khởi động lại service khi đổi danh sách.
  Cột batch (nếu có) được ghi vào _meta capture_start của mỗi phiên.
- Mất điện/tắt đột ngột: khi dừng êm (SIGINT/systemctl stop) nhịp tim cuối có "stopped": true. Lúc khởi động,
  nếu nhịp tim cuối KHÔNG có cờ đó -> lần trước tắt đột ngột: ghi một dòng vào data/raw/_incidents.jsonl
  (thời điểm nhịp tim cuối, số phút gián đoạn, các phiên chưa có capture_stop). Không sửa file dữ liệu cũ;
  ingest đánh dấu phiên thiếu capture_stop bằng cột ended_clean=False.

Chạy: python -m livesp.capture.scheduler --config configs/capture.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import load_dotenv, load_yaml, resolve
from . import channels as chn
from .recorder import ChannelRecorder, StartLimiter, check_live, configure_sign_key
from .writer import atomic_write_text, fsync_dir

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
            atomic_write_text(self.path, json.dumps({"date": self.day, "count": self.count, "limit": self.limit}))

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


def _unclosed_sessions(raw_dir: Path, since_s: float) -> list[str]:
    """session_hint có capture_start nhưng chưa có capture_stop, trong các file sửa đổi từ since_s."""
    started, stopped = set(), set()
    for p in raw_dir.glob("*/*/*.jsonl"):
        try:
            if p.stat().st_mtime < since_s:
                continue
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if '"_meta"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # dòng cắt dở lúc mất điện
                    ev = (r.get("meta") or {}).get("event")
                    if ev == "capture_start":
                        started.add(r.get("session_hint"))
                    elif ev == "capture_stop":
                        stopped.add(r.get("session_hint"))
        except OSError:
            continue
    return sorted(s for s in started - stopped if s)


def detect_unclean_shutdown(raw_dir: Path, now: float | None = None) -> dict | None:
    """Đọc nhịp tim cuối; nếu lần chạy trước không dừng êm, trả bản ghi sự cố (chưa ghi ra đĩa)."""
    now = time.time() if now is None else now
    try:
        hb = json.loads((raw_dir / "_heartbeat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # lần chạy đầu, hoặc file hỏng từ phiên bản cũ (không atomic)
    if hb.get("stopped") or "ts" not in hb:
        return None
    last = float(hb["ts"])
    return {
        "event": "unclean_shutdown",
        "detected_at": int(now * 1000),
        "last_heartbeat": int(last * 1000),
        "downtime_min": round((now - last) / 60, 1),  # tối thiểu; sự cố xảy ra trong <= 60 s sau nhịp tim cuối
        "active_at_last_heartbeat": hb.get("active") or [],
        "unclosed_sessions": _unclosed_sessions(raw_dir, last - 2 * 86400),
    }


def append_incident(raw_dir: Path, incident: dict) -> None:
    p = raw_dir / "_incidents.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(incident, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    fsync_dir(p.parent)


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
        self.only_from_start = bool(cfg.get("only_from_start", False))
        self._skip_logged: set[str] = set()
        self.wanted: set[str] = set()          # kênh đang theo dõi (theo channels.csv mới nhất)
        self.info: dict[str, dict] = {}        # dòng channels.csv của từng kênh (batch, ngành...)
        self.tasks: dict[str, asyncio.Task] = {}

    def sync_channels(self, rows: dict[str, dict]) -> tuple[list[str], list[str]]:
        """Áp danh sách kênh mới: kênh mới -> bắt đầu theo dõi; kênh bị bỏ -> thôi theo dõi SAU khi phiên đang ghi
        (nếu có) kết thúc tự nhiên — không bao giờ cắt ngang phiên. Trả (thêm, bỏ)."""
        added = sorted(c for c in rows if c not in self.wanted)
        removed = sorted(c for c in self.wanted if c not in rows)
        self.wanted, self.info = set(rows), dict(rows)
        for c in added:
            t = self.tasks.get(c)
            if t is None or t.done():  # kênh bị bỏ rồi thêm lại khi watcher cũ còn đang ghi: dùng tiếp watcher cũ
                self.tasks[c] = asyncio.get_running_loop().create_task(self.watch(c), name=f"watch:{c}")
        return added, removed

    async def reload_channels(self, path: Path, every_s: float) -> None:
        """Đọc lại channels.csv định kỳ; file đang sửa dở/lỗi -> giữ danh sách cũ."""
        last = None
        while True:
            await asyncio.sleep(every_s)
            try:
                rows, warns = chn.capture_rows(chn.read_rows(path))
            except (OSError, ValueError, csv.Error) as e:
                log.warning("Không đọc được %s (%s); giữ danh sách cũ", path, e)
                continue
            if rows == last:
                continue
            for w in warns:
                log.warning("channels.csv: %s", w)
            added, removed = self.sync_channels(rows)
            last = rows
            if added or removed:
                log.info("Cập nhật danh sách kênh: +%d %s | -%d %s (phiên đang ghi của kênh bị bỏ vẫn ghi tiếp) "
                         "| đang theo dõi %d", len(added), added, len(removed), removed, len(self.wanted))

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
            left = self.quota.remaining()
            log.info("BẮT ĐẦU ghi %s (từ đầu phiên: %s, %s)", ch, from_start,
                     "không giới hạn phiên" if left is None else f"còn {left} phiên hôm nay")
            rec = None
            try:
                rec = ChannelRecorder(ch, self.cfg, from_start, start_limiter=self.limiter,
                                      batch=(self.info.get(ch) or {}).get("batch") or None)
                await rec.record()
            except Exception as e:  # noqa: BLE001
                log.exception("recorder %s lỗi: %s", ch, e)
            finally:
                if rec is None or rec.n_connects == 0:
                    self.quota.refund()
                self.active.pop(ch, None)
                self.seen_offline[ch] = False
                log.info("KẾT THÚC ghi %s", ch)

    async def _tick(self, ch: str) -> bool | None:
        """Một lần kiểm tra kênh; ghi nếu đủ điều kiện. Trả kết quả is_live (None = lỗi mạng)."""
        live = await self._check(ch)
        if live is None:
            return None
        if not live:
            self.seen_offline[ch] = True
            self._skip_logged.discard(ch)
        elif ch not in self.active and ch in self.wanted:
            if self.only_from_start and not self.seen_offline.get(ch, False):
                if ch not in self._skip_logged:  # log một lần mỗi lượt live
                    log.info("Bỏ qua %s: đang live dở (chưa thấy offline trước đó), chờ phiên sau", ch)
                    self._skip_logged.add(ch)
            elif self.sem.locked():
                log.warning("Hết slot, bỏ lượt %s (tăng max_concurrent nếu máy chịu được)", ch)
            else:
                await self._record(ch)
        return live

    async def watch(self, ch: str) -> None:
        """Theo dõi một kênh cho tới khi nó bị bỏ khỏi danh sách (phiên đang ghi luôn được ghi trọn)."""
        poll = self.cfg.get("poll_seconds", 120)
        await asyncio.sleep(random.uniform(0, poll))  # rải đều thời điểm kiểm tra
        err_backoff = poll
        while ch in self.wanted:
            if await self._tick(ch) is None:
                await asyncio.sleep(err_backoff)
                err_backoff = min(err_backoff * 2, 1800)
                continue
            err_backoff = poll
            await asyncio.sleep(poll + random.uniform(0, self.cfg.get("poll_jitter_seconds", 15)))
        self.seen_offline.pop(ch, None)
        log.info("Thôi theo dõi %s", ch)

    def write_heartbeat(self, stopped: bool = False) -> None:
        p = resolve(self.cfg.get("raw_dir", "data/raw")) / "_heartbeat.json"
        self.quota.remaining()  # sang ngày mới (giờ VN) thì đặt lại bộ đếm trước khi ghi
        atomic_write_text(p, json.dumps({"ts": time.time(), "active": list(self.active), "stopped": stopped,
                                         "sessions_today": self.quota.count, "quota": self.quota.limit,
                                         "n_watching": len(self.wanted)},
                                        ensure_ascii=False))

    async def heartbeat(self) -> None:
        while True:
            self.write_heartbeat()
            await asyncio.sleep(60)

    async def run(self, channels: list[str] | None = None) -> None:
        """channels=None: đọc cfg['channels_csv'] và tự đọc lại mỗi channels_reload_seconds.
        channels=[...]: danh sách cố định (thử nghiệm)."""
        loops = [self.heartbeat()]
        if channels is None:
            path = resolve(self.cfg["channels_csv"])
            rows, warns = chn.capture_rows(chn.read_rows(path))
            for w in warns:
                log.warning("channels.csv: %s", w)
            self.sync_channels(rows)
            loops.append(self.reload_channels(path, self.cfg.get("channels_reload_seconds", 600)))
        else:
            self.sync_channels({c: {} for c in channels})
        log.info("Theo dõi %d kênh, tối đa %d kết nối đồng thời, %s phiên/ngày, giãn cách %ss",
                 len(self.wanted), self.cfg.get("max_concurrent", 8), self.cfg.get("max_sessions_per_day") or "∞",
                 self.cfg.get("start_spacing_seconds", 30))
        try:
            await asyncio.gather(*loops)
        finally:
            # dừng êm: hủy các watcher (recorder ghi disconnect + capture_stop), rồi đánh dấu nhịp tim
            watchers = [t for t in self.tasks.values() if not t.done()]
            for t in watchers:
                t.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)
            self.write_heartbeat(stopped=True)  # lần khởi động sau không báo sự cố


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/capture.yaml")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_dotenv()
    configure_sign_key()
    cfg = load_yaml(a.config)
    raw = resolve(cfg.get("raw_dir", "data/raw"))
    incident = detect_unclean_shutdown(raw)
    if incident:
        append_incident(raw, incident)
        log.warning("Lần chạy trước tắt ĐỘT NGỘT (mất điện?): gián đoạn ~%.1f phút, %d phiên chưa đóng -> %s",
                    incident["downtime_min"], len(incident["unclosed_sessions"]), raw / "_incidents.jsonl")
    try:
        asyncio.run(Scheduler(cfg).run())
    except KeyboardInterrupt:  # systemd KillSignal=SIGINT: dừng êm, không in traceback
        log.info("Đã dừng êm (SIGINT)")


if __name__ == "__main__":
    main()

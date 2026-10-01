"""Theo dõi nhiều kênh, tự bắt đầu ghi khi kênh lên sóng, giới hạn số kết nối đồng thời.

- was_offline_before=True chỉ khi scheduler đã THẤY kênh offline rồi mới live -> phiên được ghi từ đầu
  (sai số tối đa = chu kỳ poll). Đây là căn cứ cho tiêu chí "captured_from_start".
- Ghi nhịp tim ra data/raw/_heartbeat.json mỗi phút: nếu file cũ quá 5 phút là máy/WSL đã ngủ.

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

from ..config import load_dotenv, load_yaml, resolve
from .recorder import ChannelRecorder, check_live, configure_sign_key

log = logging.getLogger("livesp.scheduler")


def read_channels(path: str) -> list[dict]:
    with open(resolve(path), encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if str(r.get("enabled", "1")).strip() in ("1", "true", "True")]


class Scheduler:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sem = asyncio.Semaphore(cfg.get("max_concurrent", 8))
        self.active: dict[str, float] = {}
        self.seen_offline: dict[str, bool] = {}

    async def _check(self, ch: str) -> bool | None:
        return await check_live(ch)

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
                    async with self.sem:
                        self.active[ch] = time.time()
                        log.info("BẮT ĐẦU ghi %s (từ đầu phiên: %s)", ch, self.seen_offline.get(ch, False))
                        try:
                            await ChannelRecorder(ch, self.cfg, self.seen_offline.get(ch, False)).record()
                        except Exception as e:  # noqa: BLE001
                            log.exception("recorder %s lỗi: %s", ch, e)
                        finally:
                            self.active.pop(ch, None)
                            self.seen_offline[ch] = False
                            log.info("KẾT THÚC ghi %s", ch)
            await asyncio.sleep(poll + random.uniform(0, 15))

    async def heartbeat(self) -> None:
        p = resolve(self.cfg.get("raw_dir", "data/raw")) / "_heartbeat.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        while True:
            p.write_text(json.dumps({"ts": time.time(), "active": list(self.active)}, ensure_ascii=False))
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
    chans = [r["channel"].lstrip("@") for r in read_channels(cfg["channels_csv"])]
    log.info("Theo dõi %d kênh, tối đa %d kết nối đồng thời", len(chans), cfg.get("max_concurrent", 8))
    asyncio.run(Scheduler(cfg).run(chans))


if __name__ == "__main__":
    main()

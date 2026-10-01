"""Ghi một phiên live của một kênh bằng TikTokLive, tự kết nối lại, ẩn danh ngay lúc ghi.

Đã kiểm chứng với TikTokLive 6.6.6 (Python 3.14) bằng cách đọc mã nguồn thư viện đã cài:
- CommentEvent.content; LikeEvent.count/.total; RoomUserSeqEvent.total (đang xem) và .total_user (lũy kế);
  GiftEvent.repeat_count/.streaking/.gift.name; JoinEvent; FollowEvent; ShareEvent; LiveEndEvent.
- user là ExtendedUser: .unique_id (= display_id, @handle), .id (số). event.user_identity có
  is_anchor / is_moderator_of_anchor. Mỗi thông điệp có common.msg_id và common.create_time (ms, giờ máy chủ).
- FollowEvent/ShareEvent/LiveEndEvent/SuperFan* được phát THÊM, TRƯỚC sự kiện gốc cùng payload
  (SocialEvent/ControlEvent/BarrageEvent/EnvelopeEvent) -> khử trùng theo msg_id.
- Mỗi lần nối (lại), máy chủ gửi kèm vài bình luận cũ (history_comment_count=6) -> cũng khử trùng theo msg_id;
  server_ts cho biết bình luận có trước lúc bắt đầu ghi hay không.
- client.connect() bắt CancelledError rồi gọi run_until_complete trên vòng lặp đang chạy (lỗi thư viện), nên
  KHÔNG bọc connect() trong wait_for: dùng start() rồi tự chờ task; hết giờ thì disconnect().
- betterproto2 to_dict() lỗi với ExtendedUser trên Python 3.14 -> tự chuyển payload bằng _plain().
- Khóa dịch vụ ký: WebDefaults.tiktok_sign_api_key (thư viện cũng tự đọc biến SIGN_API_KEY).

Lược đồ dòng ghi (đọc bởi data/ingest.py): v, type, channel, ts (ms, giờ máy), session_hint, user (băm),
text, count, total, is_host, event_class, meta; thêm server_ts, msg_id, is_mod.
Dòng _meta.meta.event: capture_start, connect, connect_failed, disconnect, capture_stop.
"connect" chỉ ghi khi đã nối được websocket, nên khoảng disconnect -> connect là thời gian mất dữ liệu thật.

Thử nhanh 5 phút:  python -m livesp.capture.recorder --channel <unique_id> --minutes 5
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import enum
import logging
import os
import random
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable

from ..config import load_dotenv, load_yaml
from .privacy import clean_comment_text, get_salt, hash_id, scrub_payload
from .writer import JsonlWriter

log = logging.getLogger("livesp.capture")

SCHEMA_VERSION = 2  # 2: thêm server_ts, msg_id, is_mod; khử trùng msg_id; connect ghi khi đã nối được

# tên lớp sự kiện TikTokLive -> type trong lược đồ của dự án; lớp khác -> "other"
EVENT_TYPES = {
    "CommentEvent": "comment", "LikeEvent": "like", "JoinEvent": "join", "ShareEvent": "share",
    "FollowEvent": "follow", "GiftEvent": "gift", "RoomUserSeqEvent": "viewer", "LiveEndEvent": "live_end",
}
# Không nghe: bản sao thô của mọi thông điệp và sự kiện kết nối (đã ghi bằng _meta).
SKIP_CLASSES = {"WebsocketResponseEvent", "ConnectEvent", "DisconnectEvent"}
# Thuộc tính văn bản của sự kiện "other" (RoomEvent/NoticeEvent/RoomNotifyEvent.content, SystemEvent.message)
OTHER_TEXT_ATTRS = ("content", "message")
DEDUP_SIZE = 50_000
START_TIMEOUT_S = 60
LIVE_CHECK_TIMEOUT_S = 30


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _plain(obj, depth: int = 0, max_depth: int = 8):
    """Message betterproto (dataclass) -> dict/list thuần, snake_case; bỏ bytes và giá trị mặc định."""
    if isinstance(obj, enum.Enum):
        return obj.name
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (bytes, bytearray)) or depth >= max_depth:
        return None
    if isinstance(obj, (list, tuple)):
        items = (_plain(x, depth + 1, max_depth) for x in obj)
        return [x for x in items if x not in (None, "", [], {})]
    if isinstance(obj, dict):
        return {str(k): _plain(v, depth + 1, max_depth) for k, v in obj.items()}
    if dataclasses.is_dataclass(obj):
        out = {}
        for f in dataclasses.fields(obj):
            v = _plain(getattr(obj, f.name, None), depth + 1, max_depth)
            if v is None or v is False or v == 0 or v in ("", [], {}):
                continue
            out[f.name] = v
        return out
    return None


def _default_client(channel: str):
    from TikTokLive import TikTokLiveClient

    return TikTokLiveClient(unique_id=channel)  # không thêm "@": thư viện tự thêm vào referer


def listen_classes() -> list[type]:
    """Mọi lớp sự kiện của thư viện (proto + tự tạo), trừ SKIP_CLASSES."""
    from TikTokLive.events import custom_events
    from TikTokLive.events.proto_events import EVENT_MAPPINGS

    classes = {c.__name__: c for c in EVENT_MAPPINGS.values()}
    for name in custom_events.__all__:
        c = getattr(custom_events, name, None)
        if isinstance(c, type):
            classes[name] = c
    return [c for n, c in sorted(classes.items()) if n not in SKIP_CLASSES]


def _known_methods() -> set[str]:
    try:
        from TikTokLive.events.proto_events import EVENT_MAPPINGS
    except ImportError:
        return set()
    return set(EVENT_MAPPINGS)


class StartLimiter:
    """Giãn cách các lần mở kết nối (phiên mới HOẶC nối lại) trên toàn bộ scheduler, chống rate limit
    của TikTok và dịch vụ ký: hai lần start() cách nhau ít nhất min_interval_s + U(0, jitter_s) giây."""

    def __init__(self, min_interval_s: float, jitter_s: float = 0.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable = asyncio.sleep):
        self.min_interval_s, self.jitter_s = float(min_interval_s), float(jitter_s)
        self.clock, self.sleep = clock, sleep
        self._next = float("-inf")
        self._lock: asyncio.Lock | None = None

    async def wait(self) -> float:
        """Chờ tới lượt; trả số giây đã chờ."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            waited = max(self._next - self.clock(), 0.0)
            if waited > 0:
                await self.sleep(waited)
            self._next = self.clock() + self.min_interval_s + random.uniform(0, self.jitter_s)
            return waited


async def close_client(client) -> None:
    """Đóng websocket và phiên HTTP. Không dùng client.close(): nó gọi run_until_complete trong vòng lặp đang chạy."""
    with contextlib.suppress(Exception):
        await client.disconnect()
    web = getattr(client, "web", None)
    if web is not None:
        with contextlib.suppress(Exception):
            await web.close()


async def check_live(channel: str, client_factory: Callable = _default_client,
                     timeout: float = LIVE_CHECK_TIMEOUT_S) -> bool | None:
    """True/False nếu biết chắc, None nếu lỗi mạng/bị chặn (đừng coi None là offline)."""
    client = client_factory(channel)
    try:
        return bool(await asyncio.wait_for(client.is_live(), timeout))
    except Exception as e:  # noqa: BLE001
        log.warning("is_live lỗi %s: %s", channel, type(e).__name__)
        return None
    finally:
        await close_client(client)


class ChannelRecorder:
    def __init__(self, channel: str, cfg: dict, was_offline_before: bool,
                 client_factory: Callable = _default_client, start_limiter: StartLimiter | None = None):
        self.channel = channel.strip().lstrip("@")
        self.cfg = cfg
        self.salt = get_salt()
        self.channel_hash = hash_id(self.channel, self.salt)
        self.was_offline_before = was_offline_before
        self.session_hint = f"{self.channel}_{datetime.now(timezone.utc):%Y%m%dT%H%M}"
        self.writer = JsonlWriter(cfg.get("raw_dir", "data/raw"), self.channel, self.session_hint,
                                  fsync_every_s=cfg.get("fsync_every_s", 2.0))
        self.store_raw_types = set(cfg.get("store_raw_types", ["other"]))
        self.client_factory = client_factory
        self.start_limiter = start_limiter
        self.n_connects = 0
        self.live_ended = False
        self.n_duplicates = 0
        self._seen: OrderedDict = OrderedDict()
        self._known: set[str] | None = None

    # ---------- ghi ----------
    def _rec(self, etype: str, event_class: str, **kw) -> dict:
        return {"v": SCHEMA_VERSION, "type": etype, "channel": self.channel, "ts": int(time.time() * 1000),
                "session_hint": self.session_hint, "event_class": event_class, **kw}

    def meta(self, event: str, **kw) -> None:
        self.writer.write(self._rec("_meta", "_meta", meta={"event": event, **kw}))

    def _is_duplicate(self, key) -> bool:
        """Nhớ DEDUP_SIZE khóa gần nhất; True nếu đã thấy."""
        if key in self._seen:
            self.n_duplicates += 1
            return True
        self._seen[key] = None
        if len(self._seen) > DEDUP_SIZE:
            self._seen.popitem(last=False)
        return False

    def _user(self, user, identity) -> tuple[str | None, bool, bool]:
        """(mã băm, is_host, is_mod). Host = chính kênh, cờ is_anchor, hoặc quản trị viên phòng."""
        if user is None:
            return None, False, False
        handle = getattr(user, "unique_id", None) or getattr(user, "display_id", None)
        if handle:
            h = hash_id(handle, self.salt)
        else:
            uid = _int(getattr(user, "id", 0))
            h = hash_id(f"id:{uid}", self.salt) if uid else None
        try:
            badge_mod = bool(getattr(user, "is_moderator", False))
        except Exception:  # noqa: BLE001  (thuộc tính tính từ badge, có thể lỗi khi thiếu dữ liệu)
            badge_mod = False
        is_mod = badge_mod or bool(getattr(identity, "is_moderator_of_anchor", False))
        is_anchor = bool(getattr(identity, "is_anchor", False))
        return h, bool((h is not None and h == self.channel_hash) or is_anchor or is_mod), is_mod

    def on_event(self, event) -> None:
        """Listener đăng ký với thư viện: không bao giờ ném lỗi (một sự kiện hỏng không được làm rớt kết nối)."""
        try:
            self.handle(event)
        except Exception:  # noqa: BLE001
            log.exception("Lỗi xử lý %s", type(event).__name__)

    def handle(self, event) -> None:
        cls = type(event).__name__
        if cls == "UnknownEvent":
            self._handle_unknown(event)
            return
        etype = EVENT_TYPES.get(cls, "other")
        if etype == "gift" and getattr(event, "streaking", False):
            return  # chỉ ghi khi chuỗi quà kết thúc (repeat_count là tổng) để không đếm trùng
        common = getattr(event, "common", None)
        msg_id = _int(getattr(common, "msg_id", 0))
        if msg_id and self._is_duplicate(msg_id):
            return
        uhash, is_host, is_mod = self._user(getattr(event, "user", None), getattr(event, "user_identity", None))
        rec = self._rec(etype, cls, user=uhash, is_host=is_host, is_mod=is_mod,
                        server_ts=_int(getattr(common, "create_time", 0)) or None, msg_id=msg_id or None)
        if etype == "comment":
            rec["text"] = clean_comment_text(getattr(event, "content", "") or "", self.salt)
        elif etype == "like":
            rec["count"] = _int(getattr(event, "count", 0))
            rec["total"] = _int(getattr(event, "total", 0)) or None
        elif etype == "viewer":
            rec["total"] = _int(getattr(event, "total", 0))
            rec["meta"] = {"total_user": _int(getattr(event, "total_user", 0)) or None,
                           "popularity": _int(getattr(event, "popularity", 0)) or None}
        elif etype == "gift":
            gift = getattr(event, "gift", None)
            rec["count"] = _int(getattr(event, "repeat_count", 0)) or 1
            rec["meta"] = {"gift": getattr(gift, "name", None) or None,
                           "gift_id": _int(getattr(event, "gift_id", 0)) or None,
                           "diamonds": _int(getattr(gift, "diamond_count", 0)) or None}
        elif etype == "live_end":
            self.live_ended = True
        elif etype == "other":
            for attr in OTHER_TEXT_ATTRS:
                v = getattr(event, attr, None)
                if isinstance(v, str) and v:
                    rec["text"] = clean_comment_text(v, self.salt)
                    break
        if etype in self.store_raw_types:
            rec["raw"] = scrub_payload(_plain(event), self.salt)
        self.writer.write(rec)

    def _handle_unknown(self, event) -> None:
        """UnknownEvent mang cả gói phản hồi -> ghi mỗi thông điệp chưa được thư viện hỗ trợ một lần (chỉ tên method)."""
        if self._known is None:
            self._known = _known_methods()
        raw = getattr(event, "raw", None)
        for i, m in enumerate(getattr(raw, "messages", None) or []):
            method = getattr(m, "method", "") or ""
            if method in self._known:
                continue
            key = _int(getattr(m, "msg_id", 0)) or ("raw", id(raw), i)
            if self._is_duplicate(key):
                continue
            self.writer.write(self._rec("other", f"Unknown:{method}", user=None, is_host=False, is_mod=False,
                                        msg_id=key if isinstance(key, int) else None))

    # ---------- kết nối ----------
    async def _session(self, deadline: float | None, attempt: int) -> tuple[str, bool]:
        """Một lần nối. Trả (lý do kết thúc, đã nối được hay chưa). Luôn ghi disconnect nếu đã ghi connect."""
        from TikTokLive.client.errors import UserOfflineError

        client = self.client_factory(self.channel)
        for c in listen_classes():
            client.add_listener(c, self.on_event)
        connected, reason = False, "cancelled"
        try:
            if self.start_limiter is not None:
                await self.start_limiter.wait()
            try:
                task = await asyncio.wait_for(client.start(fetch_live_check=True), START_TIMEOUT_S)
            except UserOfflineError:
                reason = "offline"
            except asyncio.TimeoutError:
                reason = "start_timeout"
            except Exception as e:  # noqa: BLE001
                reason = f"start_error:{type(e).__name__}"
                log.warning("%s không nối được: %s %s", self.channel, type(e).__name__, e)
            if reason != "cancelled":
                self.meta("connect_failed", attempt=attempt, reason=reason)
                return reason, False
            connected = True
            self.n_connects += 1
            self.meta("connect", attempt=attempt, was_offline_before=self.was_offline_before,
                      room_id=getattr(client, "room_id", None))
            timeout = None if deadline is None else max(deadline - time.time(), 0)
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if not done:
                reason = "deadline"
            elif task.cancelled():
                reason = "ws_cancelled"
            elif task.exception() is not None:
                reason = f"ws_error:{type(task.exception()).__name__}"
                log.warning("%s mất kết nối: %s", self.channel, task.exception())
            else:
                reason = "live_end" if self.live_ended else "ws_closed"
            return reason, True
        finally:
            await close_client(client)
            if connected:
                self.meta("disconnect", reason=reason)

    async def _sleep(self, seconds: float, deadline: float | None) -> None:
        if deadline is not None:
            seconds = min(seconds, max(deadline - time.time(), 0))
        await asyncio.sleep(seconds)

    async def record(self, max_minutes: float | None = None) -> None:
        """Nối, ghi, nối lại với backoff; dừng khi live kết thúc, offline quá offline_grace_minutes, hoặc hết giờ."""
        deadline = time.time() + max_minutes * 60 if max_minutes else None
        grace = self.cfg.get("offline_grace_minutes", 15) * 60
        backoff, offline_since, attempt = 5.0, None, 0

        def past_deadline() -> bool:
            return deadline is not None and time.time() >= deadline

        self.meta("capture_start", was_offline_before=self.was_offline_before)
        try:
            while not self.live_ended and not past_deadline():
                attempt += 1
                reason, connected = await self._session(deadline, attempt)
                if self.live_ended or past_deadline():
                    break
                live = False if reason == "offline" else await check_live(self.channel, self.client_factory)
                if live is False:
                    offline_since = offline_since or time.time()
                    if time.time() - offline_since > grace:
                        break
                else:
                    offline_since = None
                if connected:
                    backoff = 5.0
                await self._sleep(backoff + random.uniform(0, 3), deadline)
                backoff = min(backoff * 2, 60.0)
        finally:
            self.meta("capture_stop", live_ended=self.live_ended, n_written=self.writer.n_written + 1,
                      n_duplicates=self.n_duplicates, attempts=attempt)
            self.writer.close()


def configure_sign_key() -> None:
    """Khóa dịch vụ ký (nếu có) giúp nới giới hạn tần suất. TikTokLive 6.6: WebDefaults.tiktok_sign_api_key."""
    key = os.environ.get("TIKTOK_SIGN_API_KEY")
    if not key:
        return
    try:
        from TikTokLive.client.web.web_settings import WebDefaults

        WebDefaults.tiktok_sign_api_key = key
    except Exception as e:  # noqa: BLE001
        log.warning("Không đặt được TIKTOK_SIGN_API_KEY: %s", e)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ghi một kênh trong N phút (thử adapter TikTokLive).")
    ap.add_argument("--channel", required=True)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--config", default="configs/capture.yaml")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # mỗi request một dòng URL dài
    load_dotenv()
    configure_sign_key()
    rec = ChannelRecorder(a.channel, load_yaml(a.config), was_offline_before=False)
    asyncio.run(rec.record(max_minutes=a.minutes))
    print(f"Đã ghi {rec.writer.n_written} dòng ({rec.n_duplicates} trùng bỏ qua), session_hint={rec.session_hint}")


if __name__ == "__main__":
    main()

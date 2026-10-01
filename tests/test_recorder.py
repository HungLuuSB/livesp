import asyncio
import contextlib
import dataclasses
import enum
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from livesp.capture import privacy, recorder

SALT = "unit-test-salt-0123456789"
CHANNEL = "shop.test"


# ---- sự kiện giả: tên lớp trùng tên lớp TikTokLive, thuộc tính theo 6.6.x ----
def _common(msg_id, create_time=1_700_000_000_000):
    return SimpleNamespace(msg_id=msg_id, create_time=create_time)


def _user(handle, uid=0, is_moderator=False):
    return SimpleNamespace(unique_id=handle, display_id=handle, id=uid, nickname="Tên Thật",
                           is_moderator=is_moderator)


class CommentEvent(SimpleNamespace): pass
class LikeEvent(SimpleNamespace): pass
class RoomUserSeqEvent(SimpleNamespace): pass
class GiftEvent(SimpleNamespace): pass
class LiveEndEvent(SimpleNamespace): pass
class ControlEvent(SimpleNamespace): pass
class RoomEvent(SimpleNamespace): pass
class UnknownEvent(SimpleNamespace): pass


def read_jsonl(root: Path) -> list[dict]:
    rows = []
    for p in sorted(root.rglob("*.jsonl")):
        rows += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


class RecorderTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {privacy.SALT_ENV: SALT})
        self.env.start()
        self.cfg = {"raw_dir": str(self.root), "store_raw_types": ["other"], "offline_grace_minutes": 15}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def make(self, **kw) -> recorder.ChannelRecorder:
        return recorder.ChannelRecorder("@" + CHANNEL, {**self.cfg, **kw.pop("cfg", {})}, False, **kw)

    def rows(self, rec) -> list[dict]:
        rec.writer.close()
        return read_jsonl(self.root)


class TestHandle(RecorderTestBase):
    def test_comment_hashed_and_masked(self):
        rec = self.make()
        rec.handle(CommentEvent(common=_common(1), user=_user("Lan.Nguyen"),
                                content="sdt 0912 345 678 nha @bff.cua.lan", user_identity=None))
        [r] = self.rows(rec)
        self.assertEqual(r["type"], "comment")
        self.assertEqual(r["user"], privacy.hash_id("lan.nguyen", SALT.encode()))
        self.assertIn("<SĐT>", r["text"])
        self.assertIn("@u_", r["text"])
        self.assertEqual(r["server_ts"], 1_700_000_000_000)
        self.assertEqual(r["msg_id"], 1)
        blob = json.dumps(r, ensure_ascii=False).lower()
        for leaked in ("lan.nguyen", "0912", "bff.cua.lan", "tên thật"):
            self.assertNotIn(leaked, blob)

    def test_like_viewer_gift(self):
        rec = self.make()
        rec.handle(LikeEvent(common=_common(2), user=_user("a"), count=15, total=1200))
        rec.handle(RoomUserSeqEvent(common=_common(3), total=87, total_user=1500, popularity=0))
        rec.handle(GiftEvent(common=_common(4), user=_user("b"), streaking=True, repeat_count=3))
        rec.handle(GiftEvent(common=_common(5), user=_user("b"), streaking=False, repeat_count=5, gift_id=7,
                             gift=SimpleNamespace(name="Rose", diamond_count=1)))
        like, viewer, gift = self.rows(rec)
        self.assertEqual((like["type"], like["count"], like["total"]), ("like", 15, 1200))
        self.assertEqual((viewer["type"], viewer["total"]), ("viewer", 87))
        self.assertEqual(viewer["meta"]["total_user"], 1500)
        self.assertIsNone(viewer["user"])
        self.assertEqual((gift["type"], gift["count"], gift["meta"]["gift"]), ("gift", 5, "Rose"))

    def test_host_detection(self):
        rec = self.make()
        rec.handle(CommentEvent(common=_common(10), user=_user(CHANNEL.upper()), content="chào cả nhà"))
        rec.handle(CommentEvent(common=_common(11), user=_user("mod1", is_moderator=True), content="x"))
        rec.handle(CommentEvent(common=_common(12), user=_user("khach"), content="y",
                                user_identity=SimpleNamespace(is_anchor=False, is_moderator_of_anchor=False)))
        rec.handle(CommentEvent(common=_common(13), user=_user("mod2"), content="z",
                                user_identity=SimpleNamespace(is_anchor=False, is_moderator_of_anchor=True)))
        own, mod1, guest, mod2 = self.rows(rec)
        self.assertTrue(own["is_host"])
        self.assertFalse(own["is_mod"])
        self.assertTrue(mod1["is_host"] and mod1["is_mod"])
        self.assertFalse(guest["is_host"])
        self.assertTrue(mod2["is_host"] and mod2["is_mod"])

    def test_user_without_handle_uses_numeric_id(self):
        rec = self.make()
        rec.handle(CommentEvent(common=_common(14), user=_user("", uid=987654321), content="a"))
        [r] = self.rows(rec)
        self.assertEqual(r["user"], privacy.hash_id("id:987654321", SALT.encode()))
        self.assertNotIn("987654321", json.dumps(r))

    def test_duplicate_msg_id_dropped(self):
        rec = self.make()
        ev = CommentEvent(common=_common(20), user=_user("a"), content="lịch sử khi nối lại")
        rec.handle(ev)
        rec.handle(ev)
        # LiveEndEvent phát trước ControlEvent cùng msg_id -> chỉ giữ live_end
        rec.handle(LiveEndEvent(common=_common(21)))
        rec.handle(ControlEvent(common=_common(21)))
        rows = self.rows(rec)
        self.assertEqual([r["type"] for r in rows], ["comment", "live_end"])
        self.assertEqual(rec.n_duplicates, 2)
        self.assertTrue(rec.live_ended)

    def test_other_event_text_and_raw_scrubbed(self):
        rec = self.make()
        rec.handle(RoomEvent(common=_common(30), content="@khach.a vừa mua hàng, gọi 0987654321",
                             user=None))
        [r] = self.rows(rec)
        self.assertEqual((r["type"], r["event_class"]), ("other", "RoomEvent"))
        self.assertNotIn("khach.a", r["text"])
        self.assertIn("<SĐT>", r["text"])
        self.assertIn("raw", r)  # SimpleNamespace không phải dataclass -> raw rỗng nhưng vẫn qua scrub
        self.assertNotIn("0987654321", json.dumps(r["raw"]))

    def test_unknown_event_records_method_once(self):
        rec = self.make()
        rec._known = {"WebcastChatMessage"}
        raw = SimpleNamespace(messages=[SimpleNamespace(method="WebcastChatMessage", msg_id=40),
                                        SimpleNamespace(method="WebcastNewThing", msg_id=41)])
        rec.handle(UnknownEvent(raw=raw))
        rec.handle(UnknownEvent(raw=raw))  # thư viện phát một lần cho mỗi thông điệp lạ, cùng gói
        [r] = self.rows(rec)
        self.assertEqual(r["event_class"], "Unknown:WebcastNewThing")

    def test_on_event_swallows_errors(self):
        rec = self.make()

        class BrokenEvent:
            @property
            def common(self):
                raise ValueError("hỏng")

        with self.assertLogs("livesp.capture", level="ERROR"):
            rec.on_event(BrokenEvent())


class Color(enum.IntEnum):
    RED = 1


@dataclasses.dataclass
class Inner:
    display_id: str = ""
    nickname: str = ""
    id: int = 0


@dataclasses.dataclass
class Outer:
    content: str = ""
    color: Color = Color.RED
    payload: bytes = b""
    count: int = 0
    user: Inner | None = None
    items: list = dataclasses.field(default_factory=list)


class TestPlain(unittest.TestCase):
    def test_plain_then_scrub(self):
        obj = Outer(content="hi", payload=b"\x00", user=Inner("lan.nguyen", "Lan", 42), items=[Inner()])
        plain = recorder._plain(obj)
        self.assertEqual(plain["color"], "RED")
        self.assertNotIn("payload", plain)  # bytes bỏ
        self.assertNotIn("count", plain)  # giá trị mặc định bỏ
        self.assertNotIn("items", plain)  # danh sách chỉ gồm phần tử rỗng -> bỏ
        out = privacy.scrub_payload(plain, SALT.encode())
        self.assertEqual(out["user"], {"unique_id": privacy.hash_id("lan.nguyen", SALT.encode())})


# ---- vòng lặp kết nối với client giả ----
class FakeWeb:
    async def close(self):
        pass


class FakeClient:
    def __init__(self, events=(), forever=False, start_error=None, live=False):
        self.events, self.forever, self.start_error, self.live = list(events), forever, start_error, live
        self.handler, self.task, self.web, self.room_id = None, None, FakeWeb(), 123
        self.n_listeners = 0

    def add_listener(self, cls, f):
        self.handler = f
        self.n_listeners += 1

    async def start(self, **kw):
        if self.start_error:
            raise self.start_error

        async def run():
            for ev in self.events:
                self.handler(ev)
                await asyncio.sleep(0)
            if self.forever:
                await asyncio.sleep(3600)

        self.task = asyncio.get_running_loop().create_task(run())
        return self.task

    async def disconnect(self):
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def is_live(self):
        return self.live


class TestRecordLoop(RecorderTestBase):
    def metas(self, rows):
        return [r["meta"]["event"] for r in rows if r["type"] == "_meta"]

    def test_live_end_session(self):
        clients = []

        def factory(ch):
            c = FakeClient([CommentEvent(common=_common(1), user=_user("a"), content="xin chào"),
                            LiveEndEvent(common=_common(2))])
            clients.append(c)
            return c

        rec = self.make(client_factory=factory)
        asyncio.run(rec.record(max_minutes=1))
        rows = read_jsonl(self.root)
        self.assertEqual(self.metas(rows), ["capture_start", "connect", "disconnect", "capture_stop"])
        self.assertEqual([r["type"] for r in rows if r["type"] != "_meta"], ["comment", "live_end"])
        disc = [r for r in rows if r.get("meta", {}).get("event") == "disconnect"][0]
        self.assertEqual(disc["meta"]["reason"], "live_end")
        self.assertGreater(clients[0].n_listeners, 50)  # nghe mọi lớp sự kiện của thư viện đã cài

    def test_deadline_writes_disconnect(self):
        rec = self.make(client_factory=lambda ch: FakeClient(forever=True))
        asyncio.run(rec.record(max_minutes=0.002))
        rows = read_jsonl(self.root)
        self.assertEqual(self.metas(rows), ["capture_start", "connect", "disconnect", "capture_stop"])
        disc = [r for r in rows if r.get("meta", {}).get("event") == "disconnect"][0]
        self.assertEqual(disc["meta"]["reason"], "deadline")
        self.assertEqual(rows[-1]["meta"]["reason"], "deadline")

    def test_offline_stops_after_grace(self):
        from TikTokLive.client.errors import UserOfflineError

        rec = self.make(client_factory=lambda ch: FakeClient(start_error=UserOfflineError()),
                        cfg={"offline_grace_minutes": -1})
        asyncio.run(rec.record(max_minutes=1))
        rows = read_jsonl(self.root)
        self.assertEqual(self.metas(rows), ["capture_start", "connect_failed", "capture_stop"])
        self.assertEqual(rows[-1]["meta"]["reason"], "offline_grace")

    def test_service_stop_still_writes_disconnect(self):
        """Tái hiện lỗi 01/10: systemctl restart giữa phiên -> thiếu _meta disconnect."""

        class ReraisingClient(FakeClient):
            async def disconnect(self):
                if self.task and not self.task.done():
                    self.task.cancel()
                    await self.task  # như thư viện thật: ném lại CancelledError

        rec = self.make(client_factory=lambda ch: ReraisingClient(forever=True))

        async def run_then_stop():
            t = asyncio.create_task(rec.record())
            await asyncio.sleep(0.05)
            t.cancel()  # giống SIGINT từ systemd
            with contextlib.suppress(asyncio.CancelledError):
                await t

        asyncio.run(run_then_stop())
        rows = read_jsonl(self.root)
        self.assertEqual(self.metas(rows), ["capture_start", "connect", "disconnect", "capture_stop"])
        stop = rows[-1]["meta"]
        self.assertEqual(stop["reason"], "service_stop")
        self.assertFalse(stop["live_ended"])

    def test_capture_stop_reasons(self):
        rec = self.make(client_factory=lambda ch: FakeClient([LiveEndEvent(common=_common(9))]))
        asyncio.run(rec.record(max_minutes=1))
        self.assertEqual(read_jsonl(self.root)[-1]["meta"]["reason"], "live_end")

    def test_every_connect_waits_for_limiter(self):
        from TikTokLive.client.errors import UserOfflineError

        class CountingLimiter:
            n = 0

            async def wait(self):
                CountingLimiter.n += 1
                return 0.0

        rec = self.make(client_factory=lambda ch: FakeClient(start_error=UserOfflineError()),
                        cfg={"offline_grace_minutes": 0.0001}, start_limiter=CountingLimiter())
        with mock.patch.object(recorder.random, "uniform", return_value=0), \
                mock.patch.object(recorder.ChannelRecorder, "_sleep", new=lambda self, s, d: asyncio.sleep(0)):
            asyncio.run(rec.record(max_minutes=1))
        rows = read_jsonl(self.root)
        n_attempts = sum(1 for r in rows if r.get("meta", {}).get("event") == "connect_failed")
        self.assertGreaterEqual(n_attempts, 1)
        self.assertEqual(CountingLimiter.n, n_attempts)
        self.assertEqual(rec.n_connects, 0)

    def test_check_live_none_on_error(self):
        class Boom(FakeClient):
            async def is_live(self):
                raise ConnectionError("mạng")

        self.assertIsNone(asyncio.run(recorder.check_live(CHANNEL, lambda ch: Boom())))
        self.assertTrue(asyncio.run(recorder.check_live(CHANNEL, lambda ch: FakeClient(live=True))))


class TestInstalledLibrary(RecorderTestBase):
    """Khớp với lớp THẬT của TikTokLive đã cài: nếu thư viện đổi tên thuộc tính, test này đỏ."""

    def test_real_event_classes(self):
        from TikTokLive.events import CommentEvent as RealComment, RoomUserSeqEvent as RealSeq
        from TikTokLive.proto.custom_proto import ExtendedUser

        names = {c.__name__ for c in recorder.listen_classes()}
        self.assertTrue(set(recorder.EVENT_TYPES) <= names)
        self.assertNotIn("WebsocketResponseEvent", names)

        rec = self.make()
        ev = RealComment(user=ExtendedUser(display_id="Lan.Nguyen", nickname="Lan", id=42), content="gọi 0912345678")
        rec.handle(ev)
        rec.handle(RealSeq(total=55, total_user=900))
        comment, viewer = self.rows(rec)
        self.assertEqual(comment["user"], privacy.hash_id("lan.nguyen", SALT.encode()))
        self.assertEqual(comment["text"], "gọi <SĐT>")
        self.assertEqual(viewer["total"], 55)


if __name__ == "__main__":
    unittest.main()

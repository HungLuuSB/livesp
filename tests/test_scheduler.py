import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from livesp.capture import privacy, recorder, scheduler


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.slept.append(round(s, 6))
        self.t += s


class TestStartLimiter(unittest.TestCase):
    def test_spacing_between_starts(self):
        clock = FakeClock()
        lim = recorder.StartLimiter(30, 0, clock=clock, sleep=clock.sleep)

        async def run():
            waits = [await lim.wait() for _ in range(3)]
            clock.t += 100  # lâu sau mới có lần mở tiếp -> không phải chờ
            waits.append(await lim.wait())
            return waits

        self.assertEqual(asyncio.run(run()), [0.0, 30.0, 30.0, 0.0])

    def test_concurrent_callers_are_serialized(self):
        clock = FakeClock()
        lim = recorder.StartLimiter(10, 0, clock=clock, sleep=clock.sleep)

        async def run():
            return sorted(await asyncio.gather(*(lim.wait() for _ in range(4))))

        self.assertEqual(asyncio.run(run()), [0.0, 10.0, 10.0, 10.0])
        self.assertEqual(clock.t, 1030.0)


class TestDailyQuota(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "_quota.json"
        # 01/10 23:30 giờ VN = 16:30 UTC
        self.now = datetime(2026, 10, 1, 16, 30, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def quota(self, limit=2):
        return scheduler.DailyQuota(limit, self.path, now=lambda: self.now)

    def test_limit_refund_and_persist(self):
        q = self.quota()
        self.assertTrue(q.try_take())
        self.assertTrue(q.try_take())
        self.assertFalse(q.try_take())
        q.refund()  # phiên không nối được -> hoàn lại
        self.assertEqual(q.remaining(), 1)
        # khởi động lại service trong cùng ngày: đọc lại số đã dùng
        self.assertEqual(self.quota().remaining(), 1)
        self.assertEqual(json.loads(self.path.read_text())["date"], "2026-10-01")

    def test_new_vietnam_day_resets(self):
        q = self.quota()
        q.try_take(), q.try_take()
        self.now = datetime(2026, 10, 1, 17, 1, tzinfo=timezone.utc)  # 00:01 ngày 02/10 giờ VN
        self.assertEqual(q.remaining(), 2)
        self.assertTrue(q.try_take())
        self.assertEqual(self.quota().remaining(), 1)

    def test_unlimited(self):
        q = scheduler.DailyQuota(None, None)
        self.assertTrue(all(q.try_take() for _ in range(100)))
        self.assertIsNone(q.remaining())


class FakeRecorder:
    instances = []

    def __init__(self, ch, cfg, from_start, start_limiter=None, batch=None, connects=1):
        self.ch, self.n_connects, self.batch = ch, connects, batch
        FakeRecorder.instances.append(self)

    async def record(self):
        pass


class TestSchedulerRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {privacy.SALT_ENV: "unit-test-salt-0123456789"})
        self.env.start()
        self.cfg = {"raw_dir": self.tmp.name, "max_sessions_per_day": 2, "start_spacing_seconds": 0}
        FakeRecorder.instances = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_quota_stops_new_sessions(self):
        s = scheduler.Scheduler(self.cfg)
        with mock.patch.object(scheduler, "ChannelRecorder", FakeRecorder):
            for ch in ("a", "b", "c"):
                asyncio.run(s._record(ch))
        self.assertEqual([r.ch for r in FakeRecorder.instances], ["a", "b"])
        self.assertEqual(s.quota.remaining(), 0)

    def test_failed_session_refunded(self):
        s = scheduler.Scheduler(self.cfg)
        never = lambda *a, **k: FakeRecorder(*a, **k, connects=0)  # noqa: E731
        with mock.patch.object(scheduler, "ChannelRecorder", never):
            asyncio.run(s._record("a"))
        self.assertEqual(s.quota.remaining(), 2)
        self.assertNotIn("a", s.active)


class TestHotReload(unittest.TestCase):
    """Đổi channels.csv khi đang chạy: không cắt phiên đang ghi, không cần khởi động lại."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {privacy.SALT_ENV: "unit-test-salt-0123456789"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def make(self, live: set):
        s = scheduler.Scheduler({"raw_dir": self.tmp.name, "poll_seconds": 0.01, "poll_jitter_seconds": 0,
                                 "start_spacing_seconds": 0})
        self.events = []
        self.release = None

        async def check(ch):
            return ch in live

        async def record(ch):
            s.active[ch] = 1
            self.events.append(("start", ch, (s.info.get(ch) or {}).get("batch")))
            await self.release.wait()
            self.events.append(("end", ch))
            s.active.pop(ch, None)

        s._check, s._record = check, record
        return s

    def test_add_remove_without_cutting_active_session(self):
        s = self.make(live={"a"})

        async def go():
            self.release = asyncio.Event()
            s.sync_channels({"a": {"batch": "2026-10-01"}, "b": {}})
            await asyncio.sleep(0.1)
            self.assertIn(("start", "a", "2026-10-01"), self.events)  # batch đi theo kênh
            added, removed = s.sync_channels({"c": {"batch": "2026-10-02"}})  # đổi lượt: bỏ a, b; thêm c
            self.assertEqual((added, removed), (["c"], ["a", "b"]))
            await asyncio.sleep(0.1)
            self.assertNotIn(("end", "a"), self.events)  # phiên của a KHÔNG bị cắt
            self.assertTrue(s.tasks["b"].done())  # b không ghi gì -> thôi theo dõi ngay
            self.assertFalse(s.tasks["a"].done())
            self.release.set()  # a tắt live
            await asyncio.sleep(0.1)
            self.assertIn(("end", "a"), self.events)
            self.assertTrue(s.tasks["a"].done())  # sau khi ghi trọn mới thôi theo dõi
            self.assertFalse(s.tasks["c"].done())
            for t in s.tasks.values():
                t.cancel()
            await asyncio.gather(*s.tasks.values(), return_exceptions=True)

        asyncio.run(go())
        self.assertEqual(sum(e[0] == "start" and e[1] == "a" for e in self.events), 1)

    def test_readd_while_recording_reuses_watcher(self):
        s = self.make(live={"a"})

        async def go():
            self.release = asyncio.Event()
            s.sync_channels({"a": {}})
            await asyncio.sleep(0.05)
            first = s.tasks["a"]
            s.sync_channels({})
            s.sync_channels({"a": {}})
            self.assertIs(s.tasks["a"], first)
            self.release.set()
            await asyncio.sleep(0.05)
            self.assertFalse(first.done())  # vẫn theo dõi vì kênh đã được thêm lại
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)

        asyncio.run(go())

    def test_reload_reads_csv_and_keeps_old_list_on_bad_file(self):
        csv_path = Path(self.tmp.name) / "channels.csv"
        csv_path.write_text("channel,enabled,batch\nkenh.a,1,b1\nkenh.b,0,b1\n@bad name,1,b1\n", encoding="utf-8")
        s = self.make(live=set())

        async def go():
            s.sync_channels({})
            t = asyncio.get_running_loop().create_task(s.reload_channels(csv_path, 0.01))
            await asyncio.sleep(0.05)
            self.assertEqual(s.wanted, {"kenh.a"})  # enabled=0 và tên sai bị bỏ
            csv_path.write_bytes(b"\xff\xfe\x00 garbage")  # file hỏng / đang ghi dở
            await asyncio.sleep(0.05)
            self.assertEqual(s.wanted, {"kenh.a"})
            t.cancel()
            for x in [t, *s.tasks.values()]:
                x.cancel()
            await asyncio.gather(t, *s.tasks.values(), return_exceptions=True)

        asyncio.run(go())

    def test_heartbeat_rolls_quota_to_new_day(self):
        s = scheduler.Scheduler({"raw_dir": self.tmp.name, "max_sessions_per_day": 5})
        s.quota.count, s.quota.day = 28, "2000-01-01"
        s.write_heartbeat()
        hb = json.loads((Path(self.tmp.name) / "_heartbeat.json").read_text())
        self.assertEqual(hb["sessions_today"], 0)


class TestOnlyFromStart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.recorded = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_ticks(self, only_from_start, states):
        s = scheduler.Scheduler({"raw_dir": self.tmp.name, "only_from_start": only_from_start})
        s.wanted = {"k"}
        it = iter(states)

        async def check(ch):
            return next(it)

        async def record(ch):
            self.recorded.append(ch)

        s._check, s._record = check, record

        async def go():
            return [await s._tick("k") for _ in states]

        return asyncio.run(go())

    def test_mid_session_skipped_then_next_session_recorded(self):
        # đang live lúc khởi động -> bỏ qua; offline -> live lại -> ghi
        self.assertEqual(self.run_ticks(True, [True, True, False, True]), [True, True, False, True])
        self.assertEqual(self.recorded, ["k"])

    def test_disabled_records_mid_session(self):
        self.run_ticks(False, [True])
        self.assertEqual(self.recorded, ["k"])

    def test_network_error_is_not_offline(self):
        self.run_ticks(True, [True, None, True])
        self.assertEqual(self.recorded, [])


if __name__ == "__main__":
    unittest.main()

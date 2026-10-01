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

    def __init__(self, ch, cfg, from_start, start_limiter=None, connects=1):
        self.ch, self.n_connects = ch, connects
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


if __name__ == "__main__":
    unittest.main()

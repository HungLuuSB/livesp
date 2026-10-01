import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("capture_status", ROOT / "scripts" / "capture_status.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

# 2026-10-01 10:00 giờ VN = 03:00 UTC
NOW = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
MIN = 60_000


def ms(h, m=0, d="2026-10-01"):
    """Mốc thời gian theo UTC (ms)."""
    day = datetime.strptime(d, "%Y-%m-%d").replace(hour=h, minute=m, tzinfo=timezone.utc)
    return int(day.timestamp() * 1000)


def meta(ts, event, sess="kenh_a_20261001T0100", ch="kenh_a"):
    return {"type": "_meta", "channel": ch, "session_hint": sess, "ts": ts, "meta": {"event": event}}


def ev(ts, etype, sess="kenh_a_20261001T0100", ch="kenh_a", **kw):
    return {"type": etype, "channel": ch, "session_hint": sess, "ts": ts, "user": "abcd", **kw}


def write(raw: Path, day: str, ch: str, name: str, rows: list[dict]):
    d = raw / day / ch
    d.mkdir(parents=True, exist_ok=True)
    with open(d / name, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestDisconnected(unittest.TestCase):
    def test_closed_gap_and_reconnect_count(self):
        metas = [meta(ms(1), "capture_start"), meta(ms(1), "connect"), meta(ms(1, 10), "disconnect"),
                 meta(ms(1, 13), "connect"), meta(ms(1, 30), "disconnect"), meta(ms(1, 30), "capture_stop")]
        secs, n = cs.disconnected_seconds(metas, ms(3))
        self.assertEqual(secs, 180)  # khoảng 1:30 -> stop không tính
        self.assertEqual(n, 1)

    def test_open_gap_counts_until_now(self):
        metas = [meta(ms(2), "connect"), meta(ms(2, 50), "disconnect")]
        secs, _ = cs.disconnected_seconds(metas, ms(3))
        self.assertEqual(secs, 600)


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_table_today_only(self):
        # phiên hôm nay (VN): 01:00–02:40 UTC 01/10
        write(self.raw, "2026-10-01", "kenh_a", "kenh_a_20261001T0100_01.jsonl", [
            meta(ms(1), "capture_start"), meta(ms(1), "connect"),
            ev(ms(1, 1), "comment", text="x"), ev(ms(1, 2), "viewer", total=120),
            meta(ms(1, 5), "disconnect"), meta(ms(1, 7), "connect"),
            ev(ms(2, 40), "viewer", total=150),
        ])
        # phiên hôm qua (VN): 30/09 16:00 UTC = 23:00 VN 30/09 -> loại
        write(self.raw, "2026-09-30", "kenh_b", "kenh_b_20260930T1600_16.jsonl", [
            meta(ms(16, d="2026-09-30"), "connect", sess="kenh_b_20260930T1600", ch="kenh_b"),
            ev(ms(16, 5, d="2026-09-30"), "comment", sess="kenh_b_20260930T1600", ch="kenh_b"),
        ])
        # 30/09 17:30 UTC = 00:30 VN 01/10 -> thuộc hôm nay dù nằm ở thư mục UTC 30/09
        write(self.raw, "2026-09-30", "kenh_c", "kenh_c_20260930T1730_17.jsonl", [
            meta(ms(17, 30, d="2026-09-30"), "connect", sess="kenh_c_20260930T1730", ch="kenh_c"),
            ev(ms(17, 31, d="2026-09-30"), "like", sess="kenh_c_20260930T1730", ch="kenh_c", count=3),
            meta(ms(17, 40, d="2026-09-30"), "capture_stop", sess="kenh_c_20260930T1730", ch="kenh_c"),
        ])
        files = cs.today_files(self.raw, NOW)
        t = cs.session_table(cs.load_rows(files), NOW)
        self.assertEqual(list(t["kênh"]), ["kenh_a", "kenh_c"])
        a = t.iloc[0]
        self.assertEqual((a["sự kiện"], a["bình luận"], a["người xem"]), (3, 1, 150))
        self.assertEqual((a["phút mất kết nối"], a["nối lại"]), (2.0, 1))
        self.assertEqual(a["nhịp tim cuối"], "09:40:00")
        self.assertEqual(a["trạng thái"], "đang ghi")
        self.assertEqual(t.iloc[1]["trạng thái"], "đã dừng")

    def test_heartbeat_warning(self):
        (self.raw / "_heartbeat.json").write_text(json.dumps({"ts": NOW.timestamp() - 400, "active": ["kenh_a"]}))
        text, stale = cs.render(cs.session_table(cs.load_rows([]), NOW), cs.read_heartbeat(self.raw), NOW, 5)
        self.assertTrue(stale)
        self.assertIn("CẢNH BÁO", text)
        (self.raw / "_heartbeat.json").write_text(json.dumps({"ts": NOW.timestamp() - 60, "active": []}))
        text, stale = cs.render(cs.session_table(cs.load_rows([]), NOW), cs.read_heartbeat(self.raw), NOW, 5)
        self.assertFalse(stale)
        self.assertNotIn("CẢNH BÁO", text)

    def test_missing_heartbeat_is_stale(self):
        _, stale = cs.render(cs.session_table(cs.load_rows([]), NOW), cs.read_heartbeat(self.raw), NOW, 5)
        self.assertTrue(stale)

    def test_truncated_line_ignored(self):
        write(self.raw, "2026-10-01", "kenh_a", "f.jsonl", [ev(ms(2), "comment")])
        with open(self.raw / "2026-10-01" / "kenh_a" / "f.jsonl", "a", encoding="utf-8") as f:
            f.write('{"type": "comm')
        df = cs.load_rows(cs.today_files(self.raw, NOW))
        self.assertEqual(len(df), 1)


if __name__ == "__main__":
    unittest.main()

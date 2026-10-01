"""An toàn dữ liệu khi mất điện: ghi nguyên tử, phát hiện tắt đột ngột, cờ ended_clean, sao lưu chỉ-nối-thêm."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from livesp.capture import scheduler, writer
from livesp.data import ingest

ROOT = Path(__file__).resolve().parents[1]


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestAtomicWrite(TmpDirTest):
    def test_replaces_and_leaves_no_tmp(self):
        p = self.d / "sub" / "_quota.json"
        writer.atomic_write_text(p, '{"a": 1}')
        writer.atomic_write_text(p, '{"a": 2}')
        self.assertEqual(json.loads(p.read_text()), {"a": 2})
        self.assertEqual(sorted(x.name for x in p.parent.iterdir()), ["_quota.json"])

    def test_writer_syncs_on_interval(self):
        w = writer.JsonlWriter(str(self.d), "kenh", "kenh_x", fsync_every_s=0)
        with mock.patch.object(writer.os, "fsync", wraps=os.fsync) as fs:
            w.write({"ts": 1})
            w.write({"ts": 2})
            self.assertGreaterEqual(fs.call_count, 2)
        w.close()


class TestUncleanShutdown(TmpDirTest):
    def write_session(self, hint, events):
        d = self.d / "2026-10-01" / "kenh"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{hint}_01.jsonl", "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps({"type": "_meta", "session_hint": hint, "meta": {"event": e}}) + "\n")

    def test_no_heartbeat_or_clean_stop_is_not_incident(self):
        self.assertIsNone(scheduler.detect_unclean_shutdown(self.d))
        (self.d / "_heartbeat.json").write_text(json.dumps({"ts": time.time() - 60, "stopped": True}))
        self.assertIsNone(scheduler.detect_unclean_shutdown(self.d))

    def test_power_loss_detected(self):
        self.write_session("kenh_A", ["capture_start", "connect"])  # bị cắt điện giữa chừng
        self.write_session("kenh_B", ["capture_start", "connect", "disconnect", "capture_stop"])
        with open(self.d / "2026-10-01" / "kenh" / "kenh_A_01.jsonl", "a") as f:
            f.write('{"type": "_meta", "sess')  # dòng cắt dở
        last = time.time() - 1800
        (self.d / "_heartbeat.json").write_text(json.dumps({"ts": last, "active": ["kenh"]}))
        inc = scheduler.detect_unclean_shutdown(self.d, now=last + 1800)
        self.assertEqual(inc["event"], "unclean_shutdown")
        self.assertEqual(inc["downtime_min"], 30.0)
        self.assertEqual(inc["unclosed_sessions"], ["kenh_A"])
        scheduler.append_incident(self.d, inc)
        scheduler.append_incident(self.d, inc)
        self.assertEqual(len((self.d / "_incidents.jsonl").read_text().splitlines()), 2)

    def test_scheduler_marks_clean_stop(self):
        s = scheduler.Scheduler({"raw_dir": str(self.d)})
        s.write_heartbeat(stopped=True)
        self.assertTrue(json.loads((self.d / "_heartbeat.json").read_text())["stopped"])


class TestEndedCleanFlag(unittest.TestCase):
    def test_session_table_flags_missing_capture_stop(self):
        def row(sid, ts, typ, event=None):
            return {"session_id": sid, "channel": "k", "ts": ts, "type": typ, "user": "u",
                    "total": None, "meta": {"event": event} if event else None}

        start_b = {**row("s1", 0, "_meta"), "meta": {"event": "capture_start", "batch": "2026-10-02"}}
        ev = pd.DataFrame([
            start_b, row("s1", 1000, "comment"), row("s1", 2000, "_meta", "capture_stop"),
            row("s2", 0, "_meta", "capture_start"), row("s2", 1000, "comment"),
        ])
        st = ingest.session_table(ev).set_index("session_id")
        self.assertTrue(st.loc["s1", "ended_clean"])
        self.assertFalse(st.loc["s2", "ended_clean"])
        self.assertEqual(st.loc["s1", "batch"], "2026-10-02")
        self.assertTrue(pd.isna(st.loc["s2", "batch"]))  # phiên cũ không có batch


@unittest.skipUnless(shutil.which("rsync") and shutil.which("bash"), "cần bash + rsync")
class TestBackupScript(TmpDirTest):
    def run_backup(self):
        env = {**os.environ, "LIVESP_PROJECT": str(self.proj)}
        r = subprocess.run(["bash", str(ROOT / "scripts" / "backup_data.sh"), str(self.dest)],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def setUp(self):
        super().setUp()
        self.proj, self.dest = self.d / "proj", self.d / "backup"
        raw = self.proj / "data" / "raw" / "2026-10-01" / "kenh"
        raw.mkdir(parents=True)
        (self.proj / "configs").mkdir()
        (self.proj / "configs" / "channels.csv").write_text("channel\nkenh\n")
        (self.proj / "data" / "annotations").mkdir()
        self.label = self.proj / "data" / "annotations" / "labeled_A.csv"
        self.label.write_text("id,label\n1,HOST\n")
        self.jsonl = raw / "kenh_x_01.jsonl"
        self.jsonl.write_text('{"ts": 1}\n{"ts": 2}\n')
        (self.proj / "data" / "raw" / "_heartbeat.json").write_text("{}")

    def test_copies_appends_and_never_shrinks(self):
        self.run_backup()
        b = self.dest / "data" / "raw" / "2026-10-01" / "kenh" / "kenh_x_01.jsonl"
        self.assertEqual(b.read_text(), '{"ts": 1}\n{"ts": 2}\n')
        self.assertTrue((self.dest / "configs" / "channels.csv").exists())
        self.assertFalse((self.dest / "data" / "raw" / "_heartbeat.json").exists())
        self.assertIn("n_jsonl", json.loads((self.proj / "data" / "raw" / "_last_backup.json").read_text()))
        # dữ liệu mới được nối thêm
        with open(self.jsonl, "a") as f:
            f.write('{"ts": 3}\n')
        self.run_backup()
        self.assertEqual(b.read_text().count("\n"), 3)
        # file gốc bị cắt cụt (hỏng ổ) -> bản sao lưu giữ nguyên
        self.jsonl.write_text('{"ts": 1}\n')
        self.run_backup()
        self.assertEqual(b.read_text().count("\n"), 3)

    def test_changed_label_file_keeps_old_version(self):
        self.run_backup()
        time.sleep(1.1)  # rsync so mtime theo giây
        self.label.write_text("id,label\n1,VIEWER\n")
        self.run_backup()
        self.assertIn("VIEWER", (self.dest / "data" / "annotations" / "labeled_A.csv").read_text())
        old = list((self.dest / "_versions").rglob("labeled_A.csv"))
        self.assertEqual(len(old), 1)
        self.assertIn("HOST", old[0].read_text())


if __name__ == "__main__":
    unittest.main()

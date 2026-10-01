"""Chạy toàn pipeline trên dữ liệu giả lập (make synth trước). Chỉ kiểm tra code chạy đúng, không phải kết quả."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "data" / "synth"
os.environ.setdefault("LIVESP_SALT", "synthetic-salt-not-for-real-data-000")


class TestSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SYNTH / "gold.csv").exists():
            subprocess.run([sys.executable, str(ROOT / "scripts" / "make_synthetic.py")], check=True)

    def test_end_to_end(self):
        from livesp.data import filters, ingest
        from livesp.annotate.sampling import sample_for_annotation
        from livesp.experiments import ablation
        from livesp.models.baselines import RuleClassifier
        from livesp.labels import SP_LABELS
        from livesp.panel.fe import fe_ols
        from livesp.panel.responsiveness import responsiveness
        from livesp.panel.windows import add_lags, build_panel

        ev = ingest.sessionize(ingest.load_events(ingest.iter_raw_files(SYNTH / "raw")))
        st = ingest.session_table(ev, {"min_duration_min": 30, "max_disconnected_share": 0.1})
        self.assertEqual(len(st), 12)
        self.assertTrue(st["valid"].all())
        self.assertTrue((st["disconnected_share"] > 0).all())

        com, funnel = filters.run(ev)
        self.assertTrue(com.loc[com["text"].str.contains("đã mua"), "f_system"].all())
        self.assertTrue(com.loc[com["text"].str.contains("chốt đơn nhanh"), "f_host"].all())
        self.assertTrue(com.loc[com["text"].eq("ghé shop em nha"), "f_rate_bot"].any())
        self.assertTrue(com.loc[com["text"].eq("10k 10k 10k"), "collective"].all())
        self.assertIn("- system", funnel["step"].tolist())

        s = sample_for_annotation(com, n_total=300)
        self.assertGreater(len(s), 100)
        self.assertEqual(s.groupby("session_id")["split"].nunique().max(), 1)  # một phiên chỉ thuộc một tập

        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"models": {"tfidf": {"type": "tfidf"}, "rules": {"type": "rules"}}}
            for task, models in (("sentiment", ["tfidf"]), ("sp", ["rules", "tfidf"])):
                ablation.run(task, models, ["RAW", "FULL", "RAW+teencode=naive"], 2, ["full"],
                             str(SYNTH / "gold.csv"), cfg, tmp)
                ablation.run(task, models, ["RAW", "FULL", "RAW+teencode=naive"], 2, ["full"],
                             str(SYNTH / "gold.csv"), cfg, tmp)  # lần 2: phải bỏ qua (chạy tiếp được)
                ablation.summarize(task, tmp, n_boot=100, n_perm=100)
                runs = pd.read_csv(Path(tmp) / task / "runs.csv")
                self.assertEqual(len(runs), (3 * 2 if task == "sentiment" else 3 * 2 + 2))
                self.assertTrue((Path(tmp) / task / "comparisons.csv").exists())
                self.assertTrue((Path(tmp) / task / "slices.csv").exists())

        kept = com[com["keep"]].copy()
        pred = RuleClassifier(SP_LABELS).predict(kept["text"].fillna("").tolist())
        for j, l in enumerate(SP_LABELS):
            kept[l] = pred[:, j]
        com2 = com.copy()
        for l in SP_LABELS:
            com2[l] = 0
        com2.loc[kept.index, SP_LABELS] = kept[SP_LABELS]
        resp = responsiveness(com2)
        panel = build_panel(ev, com2, 60, resp=resp, sessions=st)
        self.assertEqual(panel.groupby("session_id").size().min(), 60)  # 60 phút -> cửa sổ 0..59
        panel = add_lags(panel, ["share_HOST", "share_VIEWER"], 2)
        r = fe_ols(panel, "y_like", ["share_HOST", "share_VIEWER", "share_HOST_l1", "n_like", "log_comments"],
                   time_fe="minute_bin")
        self.assertTrue(np.isfinite(r["coef"]).all())

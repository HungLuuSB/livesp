import unittest

import numpy as np
import pandas as pd

from livesp.panel.fe import fe_ols


class TestFE(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        rows = []
        for s in range(60):
            a = rng.normal(0, 2)          # hiệu ứng phiên, tương quan với x
            for t in range(50):
                x = a + rng.normal()
                rows.append({"session_id": s, "channel": s // 3, "x": x, "y": 0.5 * x + 3 * a + rng.normal()})
        self.df = pd.DataFrame(rows)

    def test_recovers_beta_despite_confounding(self):
        r = fe_ols(self.df, "y", ["x"])
        b = r.loc[r.term == "x", "coef"].item()
        self.assertAlmostEqual(b, 0.5, delta=0.05)
        pooled = np.polyfit(self.df["x"], self.df["y"], 1)[0]
        self.assertGreater(pooled, 1.5)  # OLS gộp bị thiên lệch mạnh

    def test_matches_lsdv(self):
        d = self.df
        D = pd.get_dummies(d["session_id"], dtype=float).to_numpy()
        X = np.column_stack([d["x"].to_numpy(), D])
        beta = np.linalg.lstsq(X, d["y"].to_numpy(), rcond=None)[0][0]
        r = fe_ols(d, "y", ["x"])
        self.assertAlmostEqual(r.loc[r.term == "x", "coef"].item(), beta, places=8)
        self.assertGreater(r.loc[r.term == "x", "se"].item(), 0)

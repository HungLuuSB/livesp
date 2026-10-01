import unittest

import numpy as np

from livesp.eval.significance import approx_randomization, holm, paired_bootstrap


class TestSignificance(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.y = rng.integers(0, 3, 400)
        self.good = np.where(rng.random(400) < 0.9, self.y, rng.integers(0, 3, 400))
        self.bad = np.where(rng.random(400) < 0.5, self.y, rng.integers(0, 3, 400))

    def test_identical_not_significant(self):
        self.assertGreater(approx_randomization(self.y, self.good, self.good, n_perm=200)["p_ar"], 0.5)

    def test_clear_difference_significant(self):
        self.assertLess(approx_randomization(self.y, self.good, self.bad, n_perm=200)["p_ar"], 0.01)
        pb = paired_bootstrap(self.y, self.good, self.bad, n_boot=200)
        self.assertGreater(pb["ci_low"], 0)

    def test_holm(self):
        adj = holm([0.01, 0.04, 0.03])
        self.assertTrue(np.allclose(adj, [0.03, 0.06, 0.06]))

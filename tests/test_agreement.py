import unittest

from livesp.annotate.agreement import alpha_nominal

N = None


class TestAlpha(unittest.TestCase):
    def test_krippendorff_reference_example(self):
        # Krippendorff (2011), "Computing Krippendorff's alpha": alpha danh nghĩa = 0.743
        data = [[1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N],
                [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3],
                [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N],
                [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N]]
        self.assertAlmostEqual(alpha_nominal(data), 0.743, places=3)

    def test_perfect(self):
        self.assertEqual(alpha_nominal([[1, 0, 1], [1, 0, 1]]), 1.0)

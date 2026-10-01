import unittest

from livesp.preprocess import teencode as tc


class TestTeencode(unittest.TestCase):
    def test_naive_breaks_ambiguous_cases(self):
        self.assertIn("99 không", tc.normalize("giá 99 k", "naive"))
        self.assertIn("màu không", tc.normalize("màu hong nhạt", "naive"))
        self.assertIn("đôi đẹp", tc.normalize("đôi dep này", "naive"))
        self.assertIn("size mình", tc.normalize("size m còn ko", "naive"))
        self.assertIn("cảm ơn bao nhiêu", tc.normalize("cảm ơn bn", "naive"))

    def test_guarded_resolves_or_leaves_alone(self):
        self.assertIn("99 nghìn", tc.normalize("giá 99 k", "guarded"))
        self.assertIn("màu hồng", tc.normalize("màu hong nhạt", "guarded"))
        self.assertIn("đôi dép", tc.normalize("đôi dep này", "guarded"))
        self.assertIn("size m", tc.normalize("size m còn ko", "guarded"))
        self.assertIn("cảm ơn bạn", tc.normalize("cảm ơn bn", "guarded"))
        self.assertIn("không", tc.normalize("còn k", "guarded"))

    def test_guarded_keeps_loanwords(self):
        self.assertEqual(tc.normalize("ship nhanh sale sốc", "guarded"), "ship nhanh sale sốc")
        self.assertIn("giao hàng", tc.normalize("ship nhanh", "naive"))

    def test_contextual_requires_backend(self):
        with self.assertRaises(NotImplementedError):
            tc.normalize("abc", "contextual")

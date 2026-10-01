import unittest

from livesp.preprocess import pipeline, steps


class TestSteps(unittest.TestCase):
    def test_tone_new_and_old(self):
        self.assertEqual(steps.tone_placement("hòa thủy khỏe quý hoàng", "new"), "hoà thuỷ khoẻ quý hoàng")
        self.assertEqual(steps.tone_placement("hoà thuỷ khoẻ", "old"), "hòa thủy khỏe")
        self.assertEqual(steps.tone_placement("Hòa", "new"), "Hoà")

    def test_elongation_modes(self):
        self.assertEqual(steps.elongation("đẹppppp quáaaa xoong", "one"), "đẹp quá xoong")
        self.assertEqual(steps.elongation("đẹppppp", "two"), "đẹpp")
        self.assertEqual(steps.elongation("đẹppppp", "one_mark"), "đẹp <kéo_dài>")
        self.assertEqual(steps.elongation("đẹppppp", "keep"), "đẹppppp")

    def test_emoji(self):
        self.assertIn(":mắt_trái_tim:", steps.emoji("đẹp 😍", "vi"))
        self.assertEqual(steps.emoji("đẹp 😍", "remove"), "đẹp")
        self.assertTrue(steps.has_emoji("❤️"))

    def test_placeholders_before_teencode(self):
        s = steps.placeholders("giá 99 k, size m, còn 3 cái @u_ab12cd34")
        self.assertIn("<GIÁ>", s)
        self.assertIn("size <SIZE>", s)
        self.assertIn("<SỐ>", s)
        self.assertIn("@USER", s)

    def test_lowercase_keeps_tokens(self):
        self.assertEqual(steps.lowercase("ĐẸP <GIÁ>"), "đẹp <GIÁ>")


class TestPipeline(unittest.TestCase):
    def test_22_conditions(self):
        conds = pipeline.generate_conditions()
        self.assertEqual(len(conds), 22)
        self.assertEqual(len({c.name for c in conds}), 22)

    def test_raw_is_identity_except_whitespace(self):
        f = pipeline.build(pipeline.RAW)
        self.assertEqual(f("  Chị ơi  đẹppp 😍 "), "Chị ơi đẹppp 😍")

    def test_full(self):
        out = pipeline.build(pipeline.FULL)("Chị ơi áo này đẹppppp 😍 giá 99 k hả")
        self.assertEqual(out, "chị ơi áo này đẹp <kéo_dài> :mắt_trái_tim: giá <GIÁ> hả")

    def test_phobert_gets_segmenter(self):
        self.assertEqual(pipeline.for_model(pipeline.RAW, "phobert").segment, "rdrsegmenter")
        self.assertEqual(pipeline.for_model(pipeline.RAW, "visobert").segment, "none")

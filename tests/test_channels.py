import importlib.util
import io
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from livesp.capture import channels as chn

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("validate_channels", ROOT / "scripts" / "validate_channels.py")
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)

FRAME = {
    "category_groups": ["thoi_trang", "gia_dung"],
    "follower_tiers": {"lt100k": [0, 100000], "100k_500k": [100000, 500000],
                       "500k_1m": [500000, 1000000], "gt1m": [1000000, None]},
    "channels_per_cell": [1, 2],
}
HEADER = "channel,category_group,followers,followers_date,follower_tier,enabled,batch,note\n"


def row(ch, cat="thoi_trang", fol="1000", tier="lt100k", d="2026-10-01", en="1", batch="b1"):
    return {"channel": ch, "category_group": cat, "followers": fol, "followers_date": d,
            "follower_tier": tier, "enabled": en, "batch": batch, "note": ""}


class TestParse(unittest.TestCase):
    def test_parse_followers(self):
        cases = {"472K": 472000, "86.2K": 86200, "1.1M": 1100000, "1m": 1000000, "29k": 29000, "3249": 3249,
                 "3,249": 3249, "1.100.000": 1100000, "472,1 N": 472100, "1,1 Tr": 1100000, "2 triệu": 2000000,
                 " 15.5 K ": 15500}
        for s, n in cases.items():
            self.assertEqual(chn.parse_followers(s), n, s)
        for bad in ("", "abc", "12X", "1.2.3K", None):
            self.assertIsNone(chn.parse_followers(bad), bad)

    def test_tier_boundaries(self):
        t = FRAME["follower_tiers"]
        self.assertEqual(chn.tier_for(99999, t), "lt100k")
        self.assertEqual(chn.tier_for(100000, t), "100k_500k")  # cận dưới tính vào tầng trên
        self.assertEqual(chn.tier_for(1000000, t), "gt1m")


class TestValidate(unittest.TestCase):
    def test_errors(self):
        rows = [row("@shop.a"), row("shop.b"), row("SHOP.B"), row("shop c"), row("shop.d", cat="xe_co"),
                row("shop.e", fol="nhiều"), row("shop.f", d="01/10/2026"), row("shop.g", en="yes")]
        errors, _, _ = chn.validate(rows, FRAME)
        text = "\n".join(errors)
        for needle in ("'@'", "trùng kênh SHOP.B", "không hợp lệ (shop c)", "ngành 'xe_co'",
                       "followers 'nhiều'", "followers_date", "enabled"):
            self.assertIn(needle, text)

    def test_fix_normalizes_without_touching_names(self):
        rows = [row("shop.a", fol="472K", tier="..."), row("Shop.B", fol="1.1M", tier="lt100k")]
        errors, warnings, fixed = chn.validate(rows, FRAME)
        self.assertEqual(errors, [])
        self.assertEqual([(r["channel"], r["followers"], r["follower_tier"]) for r in fixed],
                         [("shop.a", "472000", "100k_500k"), ("Shop.B", "1100000", "gt1m")])
        self.assertTrue(any("không khớp" in w for w in warnings))
        self.assertTrue(chn.needs_fix(rows, fixed))

    def test_capture_rows_for_scheduler(self):
        rows = [row("a.shop"), row("@b.shop"), row("c.shop", en="0"), row("bad name"), row("A.SHOP")]
        out, warns = chn.capture_rows(rows)
        self.assertEqual(list(out), ["a.shop", "b.shop"])
        self.assertEqual(len(warns), 2)


class TestGrid(unittest.TestCase):
    def test_grid_counts_enabled_only(self):
        rows = [row("a"*3), row("b"*3), row("c"*3, en="0"), row("d"*3, cat="gia_dung", tier="gt1m")]
        g = chn.grid(rows, FRAME)
        self.assertEqual(g.loc["thoi_trang", "lt100k"], 2)
        self.assertEqual(g.loc["gia_dung", "gt1m"], 1)
        text, bad = chn.render_grid(g, (1, 2))
        self.assertEqual(bad, 6)  # 8 ô, đạt 2
        self.assertIn("thiếu 1", text)
        self.assertIn("Tổng: 3 kênh đang bật / mục tiêu 8–16", text)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.csv = d / "channels.csv"
        self.cfg = d / "capture.yaml"
        self.cfg.write_text(textwrap.dedent(f"""\
            channels_csv: {self.csv}
            sampling_frame:
              category_groups: [thoi_trang]
              follower_tiers:
                lt100k: [0, 100000]
                gt100k: [100000, null]
              channels_per_cell: [1, 1]
            """), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = vc.main(["--config", str(self.cfg), *args])
        return code, out.getvalue()

    def test_exit_codes_and_fix(self):
        self.csv.write_text(HEADER + "shop.a,thoi_trang,29K,2026-10-01,...,1,b1,\n", encoding="utf-8")
        code, out = self.run_cli()
        self.assertEqual(code, 2)  # thiếu ô gt100k
        self.assertIn("--fix", out)
        self.assertIn("29K", self.csv.read_text())  # không --fix -> không ghi
        code, out = self.run_cli("--fix")
        self.assertIn("shop.a,thoi_trang,29000,2026-10-01,lt100k,1,b1,", self.csv.read_text())
        with open(self.csv, "a", encoding="utf-8") as f:
            f.write('shop.b,thoi_trang,1.2M,2026-10-01,,1,b1,"ghi chú, có ""ngoặc"""\n')
        code, out = self.run_cli("--fix")
        self.assertEqual(code, 0)
        self.assertIn('"ghi chú, có ""ngoặc"""', self.csv.read_text())  # ghi chú giữ nguyên
        with open(self.csv, "a", encoding="utf-8") as f:
            f.write("@shop.a,thoi_trang,10,2026-10-01,lt100k,1,b1,\n")
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("LỖI:", out)


if __name__ == "__main__":
    unittest.main()

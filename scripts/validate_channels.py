"""Kiểm tra configs/channels.csv theo khung mẫu (configs/capture.yaml -> sampling_frame) và in bảng ô còn thiếu.

Kiểm tra: tên kênh (không '@', hợp lệ, không trùng), ngành có trong khung, followers đọc được, follower_tier khớp
followers, followers_date là ngày, enabled 0/1. Bảng: số kênh đang bật mỗi ô ngành × tầng, đánh dấu thiếu/thừa.

  python scripts/validate_channels.py            # chỉ kiểm tra
  python scripts/validate_channels.py --fix      # quy đổi followers ("472K" -> 472000) và điền/sửa follower_tier

--fix KHÔNG sửa tên kênh hay ngành; ghi file nguyên tử (bản cũ còn trong bản sao lưu D:/_versions).
Scheduler tự đọc lại channels.csv mỗi channels_reload_seconds — không cần khởi động lại service sau khi sửa.

Mã thoát: 0 = đạt hết; 1 = có lỗi dữ liệu; 2 = dữ liệu đúng nhưng còn ô chưa đạt 8–10 kênh.
"""
from __future__ import annotations

import argparse
import sys

from livesp.capture import channels as chn
from livesp.capture.writer import atomic_write_text
from livesp.config import load_yaml, resolve


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kiểm tra configs/channels.csv theo khung mẫu.")
    ap.add_argument("--config", default="configs/capture.yaml")
    ap.add_argument("--csv", default=None, help="mặc định: channels_csv trong config")
    ap.add_argument("--fix", action="store_true", help="quy đổi followers và điền follower_tier rồi ghi lại file")
    a = ap.parse_args(argv)

    cfg = load_yaml(a.config)
    frame = cfg["sampling_frame"]
    path = resolve(a.csv or cfg["channels_csv"])
    rows = chn.read_rows(path)
    errors, warnings, fixed = chn.validate(rows, frame)

    if chn.needs_fix(rows, fixed):
        if a.fix:
            atomic_write_text(path, chn.to_csv_text(fixed))
            print(f"Đã chuẩn hóa followers/follower_tier và ghi lại {path}")
            warnings = [w for w in warnings if "follower_tier" not in w]
        else:
            print("Có followers/follower_tier chưa chuẩn -> chạy lại với --fix để tự quy đổi.")

    print(f"{len(rows)} dòng, {sum(chn.enabled(r) for r in rows)} kênh đang bật\n")
    for e in errors:
        print("LỖI:", e)
    for w in warnings:
        print("Cảnh báo:", w)
    if errors or warnings:
        print()

    text, bad = chn.render_grid(chn.grid(fixed, frame), tuple(frame["channels_per_cell"]))
    print(text)
    if errors:
        return 1
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

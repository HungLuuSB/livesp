"""Sinh dữ liệu GIẢ LẬP đúng lược đồ thô để chạy thử toàn bộ pipeline trước khi có dữ liệu thật.

Tạo: data/synth/raw/... (sự kiện JSONL) và data/synth/gold.csv (nhãn "vàng" suy từ mẫu câu).
KHÔNG dùng kết quả trên dữ liệu này cho bất kỳ kết luận nào — nó chỉ để kiểm tra code chạy đúng.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LIVESP_SALT", "synthetic-salt-not-for-real-data-000")

from livesp.capture.privacy import clean_comment_text, get_salt, hash_id  # noqa: E402

T = {  # (câu, nhãn SP, cảm xúc)
    "host": [("c ơi áo này còn size L k", "HOST TRANS", "neu"), ("chị ơi cho em xem màu hồng", "HOST TRANS", "neu"),
             ("shop ơi ib em với", "HOST TRANS", "neu"), ("chị nói dễ thương ghê", "HOST AFFECT", "pos"),
             ("ad ơi mã giảm giá đâu", "HOST TRANS", "neu"), ("c ơi váy này dài bn", "HOST TRANS", "neu")],
    "viewer": [("@lan.nguyen mua đi bà", "VIEWER", "pos"), ("mn ơi hàng đẹp nha", "VIEWER AFFECT", "pos"),
               ("cả nhà ơi chốt lẹ", "VIEWER TRANS", "neu"), ("@thu_ha bà lấy màu gì", "VIEWER TRANS", "neu")],
    "affect": [("đẹppppp quáaaa 😍😍", "AFFECT", "pos"), ("hahaha dễ thương xỉu", "AFFECT", "pos"),
               ("trời ơi mê quá ❤️", "AFFECT", "pos"), ("huhu hết hàng rồi 😭", "AFFECT", "neg")],
    "self": [("con mình 5 tuổi mặc vừa lắm", "SELF", "pos"), ("mình cao 1m6 nặng 50kg mặc size gì", "SELF TRANS", "neu"),
             ("hôm qua nhận hàng rồi ưng lắm", "SELF AFFECT", "pos")],
    "trans": [("giá bn vậy", "TRANS", "neu"), ("chốt 2 cái", "TRANS", "neu"), ("size m còn k", "TRANS", "neu"),
              ("99 k hả", "TRANS", "neu"), ("màu hong còn không", "TRANS", "neu"), ("đôi dep này bao nhiêu", "TRANS", "neu"),
              ("shop giao chậm quá", "TRANS", "neg"), ("hàng lỗi rồi", "", "neg")],
    "filler": [("ok", "", "neu"), ("xem", "", "neu"), ("mới vào", "", "neu"), ("chấm", "", "neu")],
}
WEIGHTS = {"host": 0.18, "viewer": 0.12, "affect": 0.15, "self": 0.07, "trans": 0.33, "filler": 0.15}


def main(out: str = "data/synth", n_channels: int = 4, sessions_per_channel: int = 3, minutes: int = 60, seed: int = 7):
    rng = random.Random(seed)
    salt = get_salt()
    out = ROOT / out
    raw = out / "raw"
    gold_rows = {}
    t0 = 1_760_000_000_000
    for c in range(n_channels):
        ch = f"synth_shop_{c}"
        users = [f"viewer_{c}_{i}" for i in range(150)]
        for s in range(sessions_per_channel):
            start = t0 + (c * 10 + s) * 86_400_000
            hint = f"{ch}_S{s}"
            path = raw / f"2026-10-{s + 1:02d}" / ch / f"{hint}_00.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            recs = [{"type": "_meta", "ts": start, "meta": {"event": "capture_start", "was_offline_before": True}},
                    {"type": "_meta", "ts": start, "meta": {"event": "connect", "was_offline_before": True}}]
            viewers = rng.randint(80, 400)
            for m in range(minutes):
                base = start + m * 60_000
                viewers = max(10, int(viewers * rng.uniform(0.93, 1.08)))
                recs.append({"type": "viewer", "ts": base + 1000, "total": viewers})
                recs += [{"type": "like", "ts": base + rng.randint(0, 59_000), "user": rng.choice(users), "count": rng.randint(1, 15)}
                         for _ in range(rng.randint(0, 6))]
                recs += [{"type": t, "ts": base + rng.randint(0, 59_000), "user": rng.choice(users)}
                         for t in ("join", "share", "follow") for _ in range(rng.randint(0, 3))]
                for _ in range(rng.randint(3, 12)):
                    kind = rng.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
                    text, labs, sent = rng.choice(T[kind])
                    recs.append({"type": "comment", "ts": base + rng.randint(0, 59_000), "user": rng.choice(users),
                                 "text": text, "_labs": labs, "_sent": sent})
                if rng.random() < 0.15:
                    recs.append({"type": "comment", "ts": base + 500, "user": None, "text": "user đã mua sản phẩm"})
                if rng.random() < 0.10:
                    recs.append({"type": "comment", "ts": base + 800, "user": ch, "text": "chốt đơn nhanh cả nhà ơi"})
            for k in range(12):  # hô tập thể
                recs.append({"type": "comment", "ts": start + 20 * 60_000 + k * 3000, "user": users[k], "text": "10k 10k 10k"})
            for k in range(8):  # bot tốc độ
                recs.append({"type": "comment", "ts": start + 30 * 60_000 + k * 500, "user": "spam_bot", "text": "ghé shop em nha"})
            recs.append({"type": "_meta", "ts": start + 25 * 60_000, "meta": {"event": "disconnect"}})
            recs.append({"type": "_meta", "ts": start + 25 * 60_000 + 20_000, "meta": {"event": "connect"}})
            recs.sort(key=lambda r: r["ts"])
            with open(path, "w", encoding="utf-8") as f:
                for r in recs:
                    uh = hash_id(r.get("user"), salt) if r.get("user") else None
                    row = {"v": 1, "type": r["type"], "channel": ch, "ts": r["ts"], "session_hint": hint, "user": uh,
                           "is_host": r.get("user") == ch, "event_class": r["type"], "count": r.get("count"),
                           "total": r.get("total"), "meta": r.get("meta")}
                    if r["type"] == "comment":
                        row["text"] = clean_comment_text(r["text"], salt)
                        if "_labs" in r:
                            gold_rows[(hint, r["ts"], uh)] = (row["text"], r["_labs"], r["_sent"])
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    import pandas as pd

    rows = [{"session_id": k[0], "ts": k[1], "user": k[2], "text_raw": v[0], "labs": v[1], "sentiment": v[2]}
            for k, v in gold_rows.items()]
    gold = pd.DataFrame(rows).sample(frac=1, random_state=seed).head(1500)
    for l in ["HOST", "VIEWER", "COLLECTIVE", "AFFECT", "SELF", "TRANS"]:
        gold[l] = gold["labs"].str.split().map(lambda xs, l=l: int(l in xs))
    sessions = sorted(gold["session_id"].unique())
    split = {sid: ("test" if i % 4 == 0 else "dev" if i % 4 == 1 else "train") for i, sid in enumerate(sessions)}
    gold["split"] = gold["session_id"].map(split)
    gold["item_id"] = range(len(gold))
    gold.drop(columns=["labs"]).to_csv(out / "gold.csv", index=False)
    print(f"Dữ liệu giả lập -> {raw} ; nhãn -> {out / 'gold.csv'} ({len(gold)} mục)")


if __name__ == "__main__":
    main()

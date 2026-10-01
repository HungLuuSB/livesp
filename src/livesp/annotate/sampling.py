"""Lấy mẫu gán nhãn và chia tập theo PHIÊN.

Quy tắc:
- Chia train/dev/test theo phiên (không theo bình luận) để tránh rò rỉ giữa các tập.
- Mỗi phiên đóng góp số mẫu ~ căn bậc hai số bình luận (phiên lớn không lấn át), có trần.
- Một phần mẫu lấy từ các bình luận luật regex nghi là lớp hiếm (HOST, VIEWER, SELF) để tập test đủ mẫu.
- Người gán nhãn thấy VĂN BẢN THÔ + 3 bình luận ngay trước (ngữ cảnh), không bao giờ thấy bản chuẩn hóa.

Chạy:  python -m livesp.annotate.sampling --comments data/processed/comments --n 6000
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.ingest import load, save
from ..labels import SENTIMENT_LABELS, SP_LABELS
from ..models.baselines import priority_scores


def assign_splits(session_ids, ratios=(0.7, 0.1, 0.2), seed: int = 2026) -> dict[str, str]:
    """Gán tất định: băm (seed, session_id) -> [0,1). Thêm phiên mới không làm xáo trộn phiên cũ."""
    out = {}
    for sid in sorted(set(session_ids)):
        h = int(hashlib.sha256(f"{seed}:{sid}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        out[sid] = "train" if h < ratios[0] else ("dev" if h < ratios[0] + ratios[1] else "test")
    return out


def _context(g: pd.DataFrame, k: int = 3) -> list[str]:
    texts = g["text"].fillna("").tolist()
    return [" ⏎ ".join(texts[max(0, i - k) : i]) for i in range(len(texts))]


def sample_for_annotation(com: pd.DataFrame, n_total: int = 6000, cap: int = 120,
                          rare_share: float = 0.35, seed: int = 2026) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    kept = com[com["keep"]].sort_values(["session_id", "ts"]).copy()
    kept["context_before"] = kept.groupby("session_id", group_keys=False).apply(
        lambda g: pd.Series(_context(g), index=g.index))
    kept["_prio"] = priority_scores(kept["text"].fillna("").tolist())
    sizes = kept.groupby("session_id").size()
    alloc = np.sqrt(sizes)
    alloc = np.minimum(np.round(alloc / alloc.sum() * n_total), cap).astype(int)
    parts = []
    for sid, n in alloc.items():
        g = kept[kept["session_id"] == sid]
        n = min(n, len(g))
        n_rare = min(int(round(n * rare_share)), int((g["_prio"] > 0).sum()))
        rare = g[g["_prio"] > 0].sample(n_rare, random_state=int(rng.integers(1e9))) if n_rare else g.head(0)
        rest_pool = g.drop(rare.index)
        rest = rest_pool.sample(min(n - n_rare, len(rest_pool)), random_state=int(rng.integers(1e9)))
        parts.append(pd.concat([rare, rest]))
    s = pd.concat(parts)
    s["oversampled_rare"] = s["_prio"] > 0
    splits = assign_splits(com["session_id"].unique())
    s["split"] = s["session_id"].map(splits)
    s["item_id"] = [hashlib.sha1(f"{a}:{b}:{c}".encode()).hexdigest()[:12]
                    for a, b, c in zip(s["session_id"], s["ts"], s["user"].astype(str))]
    cols = ["item_id", "session_id", "split", "ts", "text", "context_before", "oversampled_rare"]
    return s[cols].rename(columns={"text": "text_raw"}).sample(frac=1, random_state=seed).reset_index(drop=True)


def assign_coders(sample: pd.DataFrame, coders=("A", "B", "C"), overlap_n: int = 1000,
                  check_share: float = 0.10, seed: int = 2026) -> pd.DataFrame:
    """overlap_n mục cho cả 3 người (tính alpha); phần còn lại chia đều, 10% có người thứ hai kiểm."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(sample))
    overlap, rest = idx[:overlap_n], idx[overlap_n:]
    rows = []
    for i in overlap:
        for c in coders:
            rows.append((i, c, "overlap"))
    for j, i in enumerate(rest):
        c = coders[j % len(coders)]
        rows.append((i, c, "single"))
        if rng.random() < check_share:
            rows.append((i, coders[(j + 1) % len(coders)], "check"))
    a = pd.DataFrame(rows, columns=["_i", "coder", "role"])
    out = sample.iloc[a["_i"]].reset_index(drop=True)
    out.insert(0, "coder", a["coder"].to_numpy())
    out.insert(1, "role", a["role"].to_numpy())
    for lab in SP_LABELS:
        out[lab] = ""
    out["sentiment"] = ""  # một trong: " + "/".join(SENTIMENT_LABELS)
    out["SYSTEM"] = ""
    out["UNCLEAR"] = ""
    out["note"] = ""
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--comments", default="data/processed/comments")
    ap.add_argument("--n", type=int, default=6000)
    ap.add_argument("--overlap", type=int, default=1000)
    ap.add_argument("--out", default="data/annotations")
    a = ap.parse_args()
    com = load(a.comments)
    s = sample_for_annotation(com, a.n)
    save(s, Path(a.out) / "sample_items")
    sheets = assign_coders(s, overlap_n=min(a.overlap, len(s)))
    for coder, g in sheets.groupby("coder"):
        g.drop(columns=["coder"]).to_csv(Path(a.out) / f"to_label_{coder}.csv", index=False, encoding="utf-8-sig")
    print(s["split"].value_counts().to_string())
    print(f"Đã xuất {len(s)} mục; bảng cho từng người gán ở {a.out}/to_label_*.csv (mở bằng Excel/Sheets được).")
    print("Nhãn hợp lệ cho cột sentiment:", SENTIMENT_LABELS)


if __name__ == "__main__":
    main()

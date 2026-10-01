"""Gộp bảng gán nhãn của các người gán -> nhãn vàng + báo cáo độ tin cậy.

- Mục 'overlap' (3 người): lấy đa số; mục hòa (vd sentiment 3 giá trị khác nhau) -> needs_adjudication.
- Mục 'single' + 'check': nếu hai người khác nhau -> needs_adjudication; ngược lại dùng nhãn chung.
Chạy: python -m livesp.annotate.merge --dir data/annotations
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ..data.ingest import save
from ..labels import SP_LABELS
from .agreement import alpha_per_label


def read_sheets(folder: str) -> pd.DataFrame:
    parts = []
    for p in sorted(Path(folder).glob("labeled_*.csv")):
        df = pd.read_csv(p, encoding="utf-8-sig")
        df["coder"] = p.stem.replace("labeled_", "")
        parts.append(df)
    if not parts:
        raise FileNotFoundError(f"Không thấy {folder}/labeled_*.csv (đổi tên to_label_X.csv thành labeled_X.csv khi gán xong)")
    return pd.concat(parts, ignore_index=True)


def merge(long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    for l in SP_LABELS:
        long[l] = pd.to_numeric(long[l], errors="coerce")
    long["sentiment"] = long["sentiment"].astype(str).str.strip().str.lower().replace({"nan": None})
    ov = long[long["role"] == "overlap"]
    rel = alpha_per_label(ov, "item_id", "coder", SP_LABELS) if len(ov) else pd.DataFrame()
    if len(ov):
        sent = ov.assign(sent_code=ov["sentiment"].map({"neg": 0, "neu": 1, "pos": 2}))
        rel = pd.concat([rel, alpha_per_label(sent, "item_id", "coder", ["sent_code"]).assign(label="sentiment")])
    rows = []
    for item, g in long.groupby("item_id"):
        base = g.iloc[0]
        rec = {"item_id": item, "session_id": base["session_id"], "split": base["split"], "text_raw": base["text_raw"],
               "n_coders": len(g), "needs_adjudication": False}
        for l in [*SP_LABELS, "sentiment"]:
            vc = g[l].dropna().value_counts()
            if vc.empty:
                rec[l] = None
                continue
            top = vc.index[0]
            tie = len(vc) > 1 and vc.iloc[0] == vc.iloc[1]
            if tie or (len(g) == 2 and len(vc) > 1):
                rec["needs_adjudication"] = True
            rec[l] = top
        rows.append(rec)
    gold = pd.DataFrame(rows)
    return gold, rel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/annotations")
    a = ap.parse_args()
    gold, rel = merge(read_sheets(a.dir))
    print(rel.to_string(index=False))
    print(f"{int(gold['needs_adjudication'].sum())} mục cần phân xử -> sửa trực tiếp trong gold rồi đặt needs_adjudication=False")
    save(gold, Path(a.dir) / "gold")
    save(rel, Path(a.dir) / "reliability")


if __name__ == "__main__":
    main()

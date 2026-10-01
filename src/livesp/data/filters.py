"""Sàng lọc bình luận: MỘT pipeline, đóng băng trước khi chạy mô hình, mỗi bước có mẫu kiểm chứng.

Mỗi bước chỉ GẮN CỜ (cột bool), không xóa. Cột `keep` tổng hợp quyết định cuối:
    keep = không phải tin hệ thống, không phải host/shop, không phải bot tốc độ, không phải bản gần trùng
Hô tập thể (collective) được GIỮ và gán nhãn — đó là tín hiệu hiện diện người xem khác.
Nghi seeding được GIỮ và gắn cờ — phân tích chính chạy cả có/không nhóm này.

Chạy:  python -m livesp.data.filters --events data/interim/events --out data/processed
"""
from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import is_frozen, load_yaml, resolve
from ..preprocess.steps import strip_emoji
from .ingest import load, save

DEFAULTS = {
    "system_patterns": [
        r"\bđã mua\b", r"\bvừa mua\b", r"\bđang mua\b", r"\bđã săn\b", r"\bvừa săn\b",
        r"\bđã đặt hàng\b", r"\bđã thêm vào giỏ\b",
    ],
    "rate_bot": {"max_msgs": 5, "window_s": 10},
    "near_dup": {"threshold": 0.8, "window_s": 60, "ngram": 3},
    "collective": {"min_users": 10, "window_s": 120},
    "seeding": {"min_sessions": 3, "early_minutes": 15, "praise_share": 0.5, "early_share": 0.5},
    "praise_patterns": [
        r"\bđẹp\b", r"\bxinh\b", r"\bngon\b", r"\bchất\b", r"\buy tín\b", r"\btốt\b",
        r"\bxịn\b", r"\bủng hộ\b", r"\bmê\b", r"\bthích\b", r"\bdep\b", r"\bokk*\b",
    ],
    "min_viewer_comments": 150,
}


def _norm_key(text: str) -> str:
    """Khóa so khớp hô tập thể: chữ thường, bỏ emoji/dấu câu, gộp ký tự lặp."""
    t = unicodedata.normalize("NFC", strip_emoji(str(text))).lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"(\w)\1{2,}", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _shingles(text: str, n: int) -> set[str]:
    t = _norm_key(text)
    return {t[i : i + n] for i in range(max(len(t) - n + 1, 1))} if t else set()


def flag_system(df: pd.DataFrame, patterns: list[str]) -> pd.Series:
    rx = re.compile("|".join(patterns), re.IGNORECASE | re.UNICODE)
    by_text = df["text"].fillna("").map(lambda s: bool(rx.search(s)))
    by_class = df.get("event_class", pd.Series("", index=df.index)).fillna("").str.contains(
        "Shop|Oec|Product|Order|Purchase", case=False, regex=True)
    return by_text | by_class


def flag_host(df: pd.DataFrame, extra_hashes: set[str] | None = None) -> pd.Series:
    """is_host do recorder điền (user == kênh, hoặc cờ moderator/owner); cộng danh sách thủ công."""
    base = df.get("is_host", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    if extra_hashes:
        base |= df["user"].isin(extra_hashes)
    return base


def flag_rate_bot(df: pd.DataFrame, max_msgs: int, window_s: float) -> pd.Series:
    """> max_msgs tin trong window_s giây từ cùng một người dùng trong cùng phiên."""
    out = pd.Series(False, index=df.index)
    w = int(window_s * 1000)
    for _, g in df.dropna(subset=["user"]).groupby(["session_id", "user"]):
        if len(g) <= max_msgs:
            continue
        ts = g["ts"].astype("int64").to_numpy()
        left = np.searchsorted(ts, ts - w, side="left")
        counts = np.arange(len(ts)) - left + 1
        out.loc[g.index[counts > max_msgs]] = True
    return out


def flag_near_dup(df: pd.DataFrame, threshold: float, window_s: float, ngram: int) -> pd.Series:
    """Bản gần trùng (Jaccard 3-gram ký tự >= ngưỡng) của CHÍNH người đó trong window_s giây; giữ bản đầu.

    So sánh chính xác trong cửa sổ theo người dùng là đủ rẻ; MinHash chỉ cần khi so chéo người dùng.
    """
    out = pd.Series(False, index=df.index)
    w = window_s * 1000
    for _, g in df.dropna(subset=["user"]).groupby(["session_id", "user"]):
        if len(g) < 2:
            continue
        hist: list[tuple[int, set[str]]] = []
        for idx, ts, text in zip(g.index, g["ts"].astype("int64"), g["text"].fillna("")):
            sh = _shingles(text, ngram)
            hist = [(t, s) for t, s in hist if ts - t <= w]
            if sh and any(len(sh & s) / len(sh | s) >= threshold for _, s in hist if s):
                out.loc[idx] = True
            else:
                hist.append((ts, sh))
    return out


def label_collective(df: pd.DataFrame, min_users: int, window_s: float) -> pd.Series:
    """Bình luận thuộc một chuỗi mà >= min_users người KHÁC NHAU gõ cùng khóa trong window_s giây."""
    out = pd.Series(False, index=df.index)
    w = int(window_s * 1000)
    keys = df["text"].fillna("").map(_norm_key)
    tmp = df.assign(_k=keys)
    tmp = tmp[tmp["_k"].str.len() > 0]
    for _, g in tmp.groupby(["session_id", "_k"]):
        if g["user"].nunique() < min_users:
            continue
        g = g.sort_values("ts")
        ts = g["ts"].astype("int64").to_numpy()
        users = g["user"].to_numpy()
        for i in range(len(g)):
            lo, hi = np.searchsorted(ts, ts[i] - w), np.searchsorted(ts, ts[i] + w, side="right")
            if len(set(users[lo:hi])) >= min_users:
                out.loc[g.index[i]] = True
    return out


def flag_seeding(df: pd.DataFrame, session_start: pd.Series, cfg: dict, praise_patterns: list[str]) -> pd.Series:
    """Nghi 'chim mồi': có mặt ở >= min_sessions phiên của CÙNG kênh, phần lớn là lời khen chung chung,
    và phần lớn gửi trong early_minutes đầu phiên. Chỉ gắn cờ — không suy diễn là chắc chắn."""
    rx = re.compile("|".join(praise_patterns), re.IGNORECASE)
    d = df.dropna(subset=["user"]).copy()
    d["_praise"] = d["text"].fillna("").map(lambda s: bool(rx.search(s)) and len(s.split()) <= 8)
    d["_early"] = (d["ts"].astype("int64") - d["session_id"].map(session_start)) <= cfg["early_minutes"] * 60_000
    agg = d.groupby(["channel", "user"]).agg(
        n_sess=("session_id", "nunique"), praise=("_praise", "mean"), early=("_early", "mean"))
    sus = agg[(agg["n_sess"] >= cfg["min_sessions"]) & (agg["praise"] >= cfg["praise_share"])
              & (agg["early"] >= cfg["early_share"])].index
    key = pd.MultiIndex.from_frame(df[["channel", "user"]].astype(str))
    sus_set = {(str(a), str(b)) for a, b in sus}
    return pd.Series([k in sus_set for k in key], index=df.index)


def run(events: pd.DataFrame, cfg: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Trả về (comments có cờ, bảng phễu)."""
    c = {**DEFAULTS, **(cfg or {})}
    com = events[events["type"] == "comment"].copy()
    com = com.sort_values(["session_id", "ts"])
    start = events[events["type"] != "_meta"].groupby("session_id")["ts"].min().astype("int64")
    com["f_system"] = flag_system(com, c["system_patterns"])
    com["f_host"] = flag_host(com, set(c.get("staff_user_hashes", []) or []))
    com["f_rate_bot"] = flag_rate_bot(com, **c["rate_bot"])
    com["f_near_dup"] = flag_near_dup(com, **c["near_dup"])
    com["collective"] = label_collective(com, **c["collective"])
    com["f_seeding"] = flag_seeding(com, start, c["seeding"], c["praise_patterns"])
    com["keep"] = ~(com["f_system"] | com["f_host"] | com["f_rate_bot"] | com["f_near_dup"])

    steps = [("raw", pd.Series(True, index=com.index))]
    mask = pd.Series(True, index=com.index)
    for name in ["f_system", "f_host", "f_rate_bot", "f_near_dup"]:
        mask = mask & ~com[name]
        steps.append((f"- {name[2:]}", mask.copy()))
    funnel = pd.DataFrame(
        [{"step": n, "remaining": int(m.sum())} for n, m in steps]
    )
    funnel["removed"] = (-funnel["remaining"].diff()).fillna(0).astype(int)
    funnel.loc[len(funnel)] = {"step": "(gắn nhãn) collective", "remaining": int((com["keep"] & com["collective"]).sum()), "removed": 0}
    funnel.loc[len(funnel)] = {"step": "(gắn cờ) seeding", "remaining": int((com["keep"] & com["f_seeding"]).sum()), "removed": 0}
    return com, funnel


def session_comment_counts(com: pd.DataFrame, min_viewer_comments: int) -> pd.DataFrame:
    n = com[com["keep"]].groupby("session_id").size().rename("n_viewer_comments")
    df = n.to_frame()
    df["meets_comment_threshold"] = df["n_viewer_comments"] >= min_viewer_comments
    return df.reset_index()


def audit_samples(com: pd.DataFrame, n: int = 200, seed: int = 13) -> pd.DataFrame:
    """Với mỗi cờ: n bình luận bị gắn cờ + n bình luận không bị gắn cờ, trộn thứ tự, để kiểm tay.

    Người kiểm điền cột `audit_correct` (1/0). precision = mean trên phần bị gắn cờ,
    recall ước lượng từ tỷ lệ bỏ sót trong phần không bị gắn cờ.
    """
    parts = []
    for flag in ["f_system", "f_host", "f_rate_bot", "f_near_dup", "collective", "f_seeding"]:
        for val in (True, False):
            sub = com[com[flag] == val]
            if sub.empty:
                continue
            s = sub.sample(min(n, len(sub)), random_state=seed)
            parts.append(s.assign(audit_flag=flag, audit_flag_value=val))
    out = pd.concat(parts) if parts else com.head(0)
    out = out.sample(frac=1, random_state=seed)
    return out[["audit_flag", "audit_flag_value", "session_id", "ts", "user", "text"]].assign(audit_correct="")


def main() -> None:
    ap = argparse.ArgumentParser(description="Sàng lọc bình luận có kiểm chứng.")
    ap.add_argument("--events", default="data/interim/events")
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--config", default="configs/filters.yaml")
    ap.add_argument("--audit", type=int, default=200, help="số mẫu kiểm tay mỗi cờ mỗi phía (0 = bỏ qua)")
    a = ap.parse_args()
    cfg = load_yaml(a.config) if resolve(a.config).exists() else {}
    if not is_frozen("filters.yaml"):
        print("LƯU Ý: configs/filters.yaml chưa đóng băng. Đóng băng trước khi chạy trên dữ liệu kiểm định (Study 2).")
    ev = load(a.events)
    com, funnel = run(ev, cfg)
    counts = session_comment_counts(com, cfg.get("min_viewer_comments", DEFAULTS["min_viewer_comments"]))
    print(funnel.to_string(index=False))
    save(com, Path(a.out) / "comments")
    save(funnel, Path(a.out) / "filter_funnel")
    save(counts, Path(a.out) / "session_comment_counts")
    if a.audit:
        p = save(audit_samples(com, a.audit), Path("data/audit") / "filter_audit")
        print(f"mẫu kiểm tay -> {p}")


if __name__ == "__main__":
    main()

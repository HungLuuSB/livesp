"""Dựng dữ liệu bảng theo cửa sổ thời gian (mặc định 60 giây) cho từng phiên.

Biến độc lập: tỷ lệ bình luận người xem mang từng nhãn SP (từ bộ phân loại), RESP, số người bình luận.
Kết cục (KHÔNG lấy từ bình luận): thay đổi log số người xem, lượt vào phòng, like, share, follow, quà.
Mọi kết cục được dịch lên 1 cửa sổ (t+1) — mô hình hỏi: SP ở t có đi trước kết cục ở t+1 không.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..labels import SP_LABELS

COUNT_TYPES = ["join", "like", "share", "follow", "gift"]
MINUTE_BINS = [-1, 9, 29, 59, 119, 239, 10_000]


def _win(ts: pd.Series, start: pd.Series, window_s: int) -> pd.Series:
    return ((ts.astype("int64") - start.astype("int64")) // (window_s * 1000)).astype(int)


def build_panel(events: pd.DataFrame, comments: pd.DataFrame, window_s: int = 60,
                labels: list[str] | None = None, resp: pd.DataFrame | None = None,
                sessions: pd.DataFrame | None = None) -> pd.DataFrame:
    labels = labels or [l for l in SP_LABELS if l in comments.columns]
    body = events[events["type"] != "_meta"]
    start = body.groupby("session_id")["ts"].min()
    end = body.groupby("session_id")["ts"].max()
    frames = []
    for sid in start.index:
        n_w = int((end[sid] - start[sid]) // (window_s * 1000)) + 1
        frames.append(pd.DataFrame({"session_id": sid, "w": np.arange(n_w)}))
    panel = pd.concat(frames, ignore_index=True)

    ev = body.assign(w=_win(body["ts"], body["session_id"].map(start), window_s))
    for t in COUNT_TYPES:
        sub = ev[ev["type"] == t]
        amt = pd.to_numeric(sub["count"], errors="coerce").fillna(1) if t in ("like", "gift") else 1
        c = sub.assign(_a=amt).groupby(["session_id", "w"])["_a"].sum().rename(f"n_{t}")
        panel = panel.merge(c, on=["session_id", "w"], how="left")
    v = ev[ev["type"] == "viewer"].assign(total=lambda x: pd.to_numeric(x["total"], errors="coerce"))
    v = v.sort_values("ts").groupby(["session_id", "w"])["total"].last().rename("viewers")
    panel = panel.merge(v, on=["session_id", "w"], how="left")
    panel["viewers"] = panel.groupby("session_id")["viewers"].ffill()

    c = comments[comments["keep"]] if "keep" in comments.columns else comments
    c = c.assign(w=_win(c["ts"], c["session_id"].map(start), window_s))
    agg = {"n_comments": ("text", "size"), "n_commenters": ("user", "nunique")}
    agg.update({f"share_{l}": (l, "mean") for l in labels})
    for extra in ("sent_pos", "collective"):
        if extra in c.columns:
            agg[f"share_{extra}"] = (extra, "mean")
    ca = c.groupby(["session_id", "w"]).agg(**agg)
    panel = panel.merge(ca, on=["session_id", "w"], how="left")

    if resp is not None and len(resp):
        r = resp.assign(w=_win(resp["ts"], resp["session_id"].map(start), window_s))
        ra = r.groupby(["session_id", "w"]).agg(n_questions=("answered_proxy", "size"),
                                                  resp_answered=("answered_proxy", lambda x: (x == 1).sum()),
                                                  resp_signal=("answered_proxy", lambda x: x.notna().sum()))
        panel = panel.merge(ra, on=["session_id", "w"], how="left")

    cnt_cols = [f"n_{t}" for t in COUNT_TYPES] + ["n_comments", "n_commenters", "n_questions", "resp_answered", "resp_signal"]
    for col in cnt_cols:
        if col in panel.columns:
            panel[col] = panel[col].fillna(0)
    share_cols = [c for c in panel.columns if c.startswith("share_")]
    panel["has_comments"] = (panel["n_comments"] > 0).astype(int)
    panel[share_cols] = panel[share_cols].fillna(0.0)
    if "resp_signal" in panel.columns:
        panel["resp_share"] = np.where(panel["resp_signal"] > 0, panel["resp_answered"] / panel["resp_signal"].clip(lower=1), 0.0)
    panel["log_comments"] = np.log1p(panel["n_comments"])
    panel["log_viewers"] = np.log1p(panel["viewers"])
    panel["minute_bin"] = pd.cut(panel["w"] * window_s / 60, MINUTE_BINS, labels=False)

    g = panel.groupby("session_id")
    panel["y_dlog_viewers"] = g["log_viewers"].shift(-1) - panel["log_viewers"]
    for t in COUNT_TYPES:
        panel[f"y_{t}"] = np.arcsinh(g[f"n_{t}"].shift(-1))
    if sessions is not None and "channel" in sessions.columns:
        panel = panel.merge(sessions[["session_id", "channel"]], on="session_id", how="left")
    return panel


def add_lags(panel: pd.DataFrame, cols: list[str], lags: int, entity: str = "session_id") -> pd.DataFrame:
    g = panel.groupby(entity)
    for c in cols:
        for k in range(1, lags + 1):
            panel[f"{c}_l{k}"] = g[c].shift(k)
    return panel

"""Proxy RESP: host có phản hồi câu hỏi của người xem không — suy ra từ hành vi TIẾP THEO của người hỏi.

Host trả lời bằng lời nên chat không chứa câu trả lời. Nhưng người hỏi thường:
    - gửi lời xác nhận ("dạ em cảm ơn c", "ok c", "vâng ạ")  -> nhiều khả năng ĐÃ được trả lời (1)
    - hỏi lại cùng câu                                         -> nhiều khả năng BỊ BỎ QUA (0)
    - im lặng                                                  -> không có tín hiệu (NaN)
Proxy CHỈ được dùng sau khi kiểm chứng trên audio nghe tay (H3c: precision >= 0,70).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

QUESTION_RE = re.compile(
    r"\?|\b(?:không|ko|k|hông|hok|chưa|nhiêu|bn|sao|mấy|nào|hả|hở|ko ạ|được không|dc k|đc k|còn không|còn k)\s*[?]*\s*$",
    re.I)
ACK_RE = re.compile(
    r"^\s*(?:dạ|vâng|ok|oke|okie|oki|okk+|cảm ơn|cám ơn|camon|tks|thanks|thank|hiểu rồi|à|à dạ|ừ|uh|"
    r"vậy hả|zậy hả|v hả|oh|ồ|để em|để mình|em lấy|mình lấy|chốt)\b", re.I)
VOC_RE = re.compile(r"\b(?:c|chị|shop|ad|admin|em|e|anh|a|sốp)\s*(?:ơi|oi|ui)\b", re.I)


def _sim(a: str, b: str) -> float:
    sa, sb = set(a.lower().split()), set(b.lower().split())
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def responsiveness(com: pd.DataFrame, window_s: float = 120, repeat_sim: float = 0.6,
                   host_col: str | None = "HOST") -> pd.DataFrame:
    """com: bình luận đã lọc (keep), có session_id, ts, user, text; tùy chọn cột dự đoán HOST (0/1).

    Trả về một dòng cho mỗi câu hỏi hướng host: answered_proxy ∈ {1, 0, NaN}, delay_s.
    """
    d = com[com["keep"]] if "keep" in com.columns else com
    d = d.sort_values(["session_id", "ts"])
    rows = []
    w = window_s * 1000
    for (sid, user), g in d.dropna(subset=["user"]).groupby(["session_id", "user"]):
        texts = g["text"].fillna("").tolist()
        ts = g["ts"].astype("int64").tolist()
        host = g[host_col].tolist() if host_col and host_col in g.columns else [None] * len(g)
        for i, t in enumerate(texts):
            is_q = bool(QUESTION_RE.search(t))
            to_host = bool(host[i]) if host[i] is not None else bool(VOC_RE.search(t))
            if not (is_q and to_host):
                continue
            ans, delay = np.nan, np.nan
            for j in range(i + 1, len(texts)):
                if ts[j] - ts[i] > w:
                    break
                if ACK_RE.search(texts[j]):
                    ans, delay = 1.0, (ts[j] - ts[i]) / 1000
                    break
                if QUESTION_RE.search(texts[j]) and _sim(t, texts[j]) >= repeat_sim:
                    ans, delay = 0.0, (ts[j] - ts[i]) / 1000
                    break
            rows.append({"session_id": sid, "user": user, "ts": ts[i], "text": t,
                         "answered_proxy": ans, "delay_s": delay})
    return pd.DataFrame(rows, columns=["session_id", "user", "ts", "text", "answered_proxy", "delay_s"])

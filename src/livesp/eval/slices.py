"""Đánh giá theo lát cắt: trả lời trực tiếp câu hỏi 'chuẩn hóa có xóa mất cái đặc biệt của miền không'.

Lát cắt được gắn trên VĂN BẢN THÔ (không phụ thuộc điều kiện tiền xử lý), nên so sánh được giữa các điều kiện.
"""
from __future__ import annotations

import re
from typing import Callable

import numpy as np
import pandas as pd

from ..preprocess.steps import has_elongation, has_emoji, strip_emoji
from ..preprocess.teencode import teencode_tokens
from .metrics import macro_f1

_VN_CHARS = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I)
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)

SLICES: dict[str, Callable[[str], bool]] = {
    "teencode": lambda t: bool(teencode_tokens(t)),
    "no_diacritics": lambda t: len(_LETTERS.findall(t)) >= 4 and not _VN_CHARS.search(t),
    "elongation": has_elongation,
    "emoji_any": has_emoji,
    "emoji_only": lambda t: has_emoji(t) and not _LETTERS.search(strip_emoji(t)),
    "short_le3": lambda t: len(t.split()) <= 3,
    "price_k": lambda t: bool(re.search(r"\d+\s?k\b", t, re.I)),
    "vocative": lambda t: bool(re.search(r"\b(?:ơi|oi|ui)\b", t, re.I)),
    "mention": lambda t: "@" in t,
}


def tag_slices(texts) -> pd.DataFrame:
    texts = ["" if t is None else str(t) for t in texts]
    return pd.DataFrame({name: [bool(f(t)) for t in texts] for name, f in SLICES.items()})


def slice_report(texts, y_true, y_pred, metric: Callable = macro_f1, min_n: int = 20) -> pd.DataFrame:
    tags = tag_slices(texts)
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    rows = [{"slice": "ALL", "n": len(yt), "score": metric(yt, yp)}]
    for name in tags.columns:
        m = tags[name].to_numpy()
        rows.append({"slice": name, "n": int(m.sum()),
                     "score": metric(yt[m], yp[m]) if m.sum() >= min_n else np.nan})
    return pd.DataFrame(rows)

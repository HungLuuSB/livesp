"""Krippendorff's alpha (thang danh nghĩa), chấp nhận thiếu dữ liệu và số người gán nhãn bất kỳ.

Cài đặt theo ma trận trùng khớp (coincidence matrix), Krippendorff (2011), "Computing Krippendorff's alpha".
Kiểm chứng: tests/test_agreement.py tái lập ví dụ chuẩn của Krippendorff (alpha danh nghĩa = 0.743).
"""
from __future__ import annotations

from collections import Counter
from itertools import permutations

import numpy as np
import pandas as pd


def alpha_nominal(data: list[list[object]] | np.ndarray) -> float:
    """data: ma trận người gán nhãn × đơn vị; None/NaN = thiếu.

    Đơn vị có < 2 giá trị bị bỏ (không so cặp được).
    """
    arr = np.asarray(data, dtype=object)
    units = []
    for j in range(arr.shape[1]):
        vals = [v for v in arr[:, j] if v is not None and not (isinstance(v, float) and np.isnan(v))]
        if len(vals) >= 2:
            units.append(vals)
    if not units:
        return float("nan")
    o: Counter = Counter()
    for vals in units:
        m = len(vals)
        for a, b in permutations(range(m), 2):
            o[(vals[a], vals[b])] += 1 / (m - 1)
    cats = sorted({c for pair in o for c in pair}, key=str)
    n_c = {c: sum(v for (a, _), v in o.items() if a == c) for c in cats}
    n = sum(n_c.values())
    d_o = sum(v for (a, b), v in o.items() if a != b)
    d_e = sum(n_c[a] * n_c[b] for a in cats for b in cats if a != b) / (n - 1)
    if d_e == 0:
        return 1.0
    return 1 - d_o / d_e


def alpha_per_label(df: pd.DataFrame, item_col: str, coder_col: str, labels: list[str]) -> pd.DataFrame:
    """Dữ liệu dạng dài: mỗi dòng = (bình luận, người gán, các cột nhãn 0/1). Trả alpha cho từng nhãn."""
    rows = []
    for lab in labels:
        wide = df.pivot_table(index=coder_col, columns=item_col, values=lab, aggfunc="first")
        mat = wide.to_numpy(dtype=object)
        mat = np.where(pd.isna(mat), None, mat)
        a = alpha_nominal(mat)
        rows.append({
            "label": lab,
            "alpha": round(a, 3),
            "n_items": int(wide.notna().sum(axis=0).ge(2).sum()),
            "prevalence": round(float(pd.to_numeric(df[lab], errors="coerce").mean()), 3),
            "meets_0.667": bool(a >= 0.667),
            "meets_0.80": bool(a >= 0.80),
        })
    return pd.DataFrame(rows)

"""Kiểm định ý nghĩa cho so sánh cặp trên CÙNG tập test (Dror và cộng sự, 2018).

- paired_bootstrap : khoảng tin cậy cho chênh lệch chỉ số giữa hai hệ thống
- approx_randomization : kiểm định hoán vị (đổi dự đoán hai hệ thống theo từng mục)
- holm : hiệu chỉnh đa so sánh Holm–Bonferroni
Chênh 0,01–0,02 macro-F1 mà p (sau Holm) > 0,05 thì KHÔNG kết luận bước tiền xử lý đó giúp/hại.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .metrics import macro_f1


def paired_bootstrap(y_true, pred_a, pred_b, metric: Callable = macro_f1, n_boot: int = 1000,
                     seed: int = 0) -> dict:
    yt, a, b = map(np.asarray, (y_true, pred_a, pred_b))
    rng = np.random.default_rng(seed)
    n = len(yt)
    obs = metric(yt, a) - metric(yt, b)
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        deltas[i] = metric(yt[idx], a[idx]) - metric(yt[idx], b[idx])
    p = 2 * min((deltas <= 0).mean(), (deltas >= 0).mean())
    return {"delta": float(obs), "ci_low": float(np.quantile(deltas, 0.025)),
            "ci_high": float(np.quantile(deltas, 0.975)), "p_boot": float(min(p, 1.0))}


def approx_randomization(y_true, pred_a, pred_b, metric: Callable = macro_f1, n_perm: int = 2000,
                         seed: int = 0) -> dict:
    yt, a, b = map(np.asarray, (y_true, pred_a, pred_b))
    rng = np.random.default_rng(seed)
    obs = abs(metric(yt, a) - metric(yt, b))
    hits = 0
    for _ in range(n_perm):
        swap = rng.random(len(yt)) < 0.5
        if a.ndim == 2:
            sw = swap[:, None]
            a2, b2 = np.where(sw, b, a), np.where(sw, a, b)
        else:
            a2, b2 = np.where(swap, b, a), np.where(swap, a, b)
        if abs(metric(yt, a2) - metric(yt, b2)) >= obs:
            hits += 1
    return {"delta_abs": float(obs), "p_ar": (hits + 1) / (n_perm + 1)}


def holm(pvals) -> np.ndarray:
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(running, 1.0)
    return adj

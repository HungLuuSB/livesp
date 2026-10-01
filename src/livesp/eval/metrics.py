"""Chỉ số đánh giá: macro-F1 (đa lớp), F1 từng nhãn (đa nhãn), khoảng tin cậy bootstrap."""
from __future__ import annotations

from typing import Callable

import numpy as np
from sklearn.metrics import f1_score


def macro_f1(y_true, y_pred) -> float:
    """Đa lớp: macro-F1. Đa nhãn (ma trận 0/1): trung bình F1 của từng nhãn."""
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    if yt.ndim == 2:
        return float(np.mean([f1_score(yt[:, j], yp[:, j], zero_division=0) for j in range(yt.shape[1])]))
    return float(f1_score(yt, yp, average="macro", zero_division=0))


def per_label_f1(y_true, y_pred, labels: list[str]) -> dict[str, float]:
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    if yt.ndim == 2:
        return {l: float(f1_score(yt[:, j], yp[:, j], zero_division=0)) for j, l in enumerate(labels)}
    scores = f1_score(yt, yp, labels=labels, average=None, zero_division=0)
    return dict(zip(labels, map(float, scores)))


def bootstrap_ci(y_true, y_pred, metric: Callable = macro_f1, n_boot: int = 1000,
                 alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    """(điểm, cận dưới, cận trên) theo bootstrap phân vị trên các mục của tập test."""
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    rng = np.random.default_rng(seed)
    n = len(yt)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        vals[b] = metric(yt[idx], yp[idx])
    return float(metric(yt, yp)), float(np.quantile(vals, alpha / 2)), float(np.quantile(vals, 1 - alpha / 2))

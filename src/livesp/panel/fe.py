"""Hồi quy hiệu ứng cố định (within) với sai số chuẩn cụm, và phân tích đa vũ trụ.

Cài bằng numpy để không phụ thuộc thư viện nặng và để kiểm chứng được (tests/test_panel.py so với LSDV).
Mô hình chính (PROPOSAL, Study 2):
    y_{s,t+1} = Σ_k β_k SP_{s,t-k} + ρ y_{s,t} + γ'X_{s,t} + α_s + λ_{bin(t)} + ε
Mỗi phiên ~300 phút nên thiên lệch Nickell do biến trễ + hiệu ứng cố định là nhỏ (O(1/T)).
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
from scipy import stats


def _demean(df: pd.DataFrame, cols: list[str], entity: str) -> pd.DataFrame:
    return df[cols] - df.groupby(entity)[cols].transform("mean")


def fe_ols(df: pd.DataFrame, y: str, X: list[str], entity: str = "session_id",
           cluster: str | None = "channel", time_fe: str | None = None) -> pd.DataFrame:
    """Ước lượng within; SE cụm CR1 theo `cluster` (mặc định kênh), df = G − 1."""
    cols = [y, *X, entity] + ([cluster] if cluster else []) + ([time_fe] if time_fe else [])
    d = df[list(dict.fromkeys(cols))].dropna().copy()
    xcols = list(X)
    if time_fe:
        dummies = pd.get_dummies(d[time_fe].astype("category"), prefix="tfe", drop_first=True, dtype=float)
        d = pd.concat([d, dummies], axis=1)
        xcols += list(dummies.columns)
    dm = _demean(d, [y, *xcols], entity)
    Xm, ym = dm[xcols].to_numpy(float), dm[y].to_numpy(float)
    keep = Xm.std(axis=0) > 1e-12
    Xm, xcols = Xm[:, keep], [c for c, k in zip(xcols, keep) if k]
    XtX_inv = np.linalg.pinv(Xm.T @ Xm)
    beta = XtX_inv @ Xm.T @ ym
    u = ym - Xm @ beta
    n, k = Xm.shape
    groups = d[cluster].to_numpy() if cluster else d[entity].to_numpy()
    uniq = pd.unique(groups)
    G = len(uniq)
    meat = np.zeros((k, k))
    for gval in uniq:
        m = groups == gval
        s = Xm[m].T @ u[m]
        meat += np.outer(s, s)
    scale = (G / (G - 1)) * ((n - 1) / (n - k)) if G > 1 else 1.0
    V = scale * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.clip(np.diag(V), 0, None))
    t = beta / np.where(se > 0, se, np.nan)
    dof = max(G - 1, 1)
    p = 2 * stats.t.sf(np.abs(t), dof)
    q = stats.t.ppf(0.975, dof)
    res = pd.DataFrame({"term": xcols, "coef": beta, "se": se, "t": t, "p": p,
                        "ci_low": beta - q * se, "ci_high": beta + q * se})
    res.attrs.update({"n": n, "n_entities": d[entity].nunique(), "n_clusters": G, "y": y})
    return res[~res["term"].str.startswith("tfe_")].reset_index(drop=True)


def reverse_direction(df: pd.DataFrame, sp_col: str, outcome_col: str, controls: list[str],
                      entity: str = "session_id", cluster: str = "channel") -> pd.DataFrame:
    """H4c: SP ở t+1 theo kết cục ở t (mô hình đối xứng), để báo hai chiều cạnh nhau."""
    d = df.copy()
    d["_sp_lead"] = d.groupby(entity)[sp_col].shift(-1)
    return fe_ols(d, "_sp_lead", [outcome_col, sp_col, *controls], entity, cluster)


def multiverse(build_fn, choices: dict[str, list], focal: str, **fe_kwargs) -> pd.DataFrame:
    """Chạy lại mô hình trên MỌI tổ hợp lựa chọn phân tích.

    build_fn(**spec) -> (panel_df, y, X). choices ví dụ:
        {"window_s": [60, 120, 300], "classifier": ["best", "second"], "seeding": ["keep", "drop"], "lags": [1, 3, 5]}
    Trả bảng hệ số của biến `focal` theo từng tổ hợp (vẽ specification curve từ bảng này).
    """
    rows = []
    keys = list(choices)
    for combo in itertools.product(*(choices[k] for k in keys)):
        spec = dict(zip(keys, combo))
        panel, y, X = build_fn(**spec)
        r = fe_ols(panel, y, X, **fe_kwargs)
        hit = r[r["term"] == focal]
        if len(hit):
            rows.append({**spec, **hit.iloc[0].to_dict(), "n": r.attrs["n"]})
    out = pd.DataFrame(rows)
    return out.sort_values("coef").reset_index(drop=True) if len(out) else out


def session_level_mixed(df: pd.DataFrame, formula: str, group: str = "channel"):
    """Cấp phiên: mô hình hỗn hợp với hiệu ứng ngẫu nhiên theo kênh (cần statsmodels)."""
    import statsmodels.formula.api as smf  # type: ignore

    return smf.mixedlm(formula, df, groups=df[group]).fit(reml=True)

"""Đọc sự kiện thô (JSONL) -> DataFrame, dựng phiên, bảng chất lượng phiên.

Lược đồ một dòng sự kiện (do capture/recorder.py ghi):
    v, type, channel, ts (ms), session_hint, user (đã băm), text, count, total, is_host, event_class, meta
type ∈ {comment, like, join, share, follow, gift, viewer, live_end, other, _meta}

Chạy:  python -m livesp.data.ingest --raw data/raw --out data/interim
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from ..config import load_yaml, resolve

EVENT_COLUMNS = ["v", "type", "channel", "ts", "session_hint", "user", "text", "count", "total",
                 "is_host", "event_class", "meta"]


def iter_raw_files(root: str | Path) -> list[Path]:
    root = resolve(root)
    return sorted([*root.rglob("*.jsonl"), *root.rglob("*.jsonl.gz")])


def _open(p: Path):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def load_events(paths: Iterable[Path]) -> pd.DataFrame:
    rows, bad = [], 0
    for p in paths:
        with _open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    bad += 1  # dòng cuối có thể bị cắt khi máy tắt đột ngột
    df = pd.DataFrame(rows)
    for c in EVENT_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["ts"] = pd.to_numeric(df["ts"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["ts"]).sort_values(["channel", "ts"]).reset_index(drop=True)
    df.attrs["bad_lines"] = bad
    return df


def sessionize(events: pd.DataFrame, gap_minutes: float = 15.0) -> pd.DataFrame:
    """Gán session_id. Ưu tiên session_hint từ recorder; nếu thiếu (dữ liệu cũ), tách theo khoảng lặng."""
    ev = events.copy()
    has_hint = ev["session_hint"].notna()
    ev["session_id"] = ev["session_hint"].where(has_hint)
    if (~has_hint).any():
        part = ev.loc[~has_hint & (ev["type"] != "_meta")].copy()
        gap = part.groupby("channel")["ts"].diff().fillna(np.inf) > gap_minutes * 60_000
        part["_n"] = gap.groupby(part["channel"]).cumsum()
        start = part.groupby(["channel", "_n"])["ts"].transform("min")
        part["session_id"] = part["channel"].astype(str) + "_" + pd.to_datetime(
            start.astype("int64"), unit="ms").dt.strftime("%Y%m%dT%H%M")
        ev.loc[part.index, "session_id"] = part["session_id"]
    return ev.dropna(subset=["session_id"])


def _disconnected_seconds(meta: pd.DataFrame) -> float:
    """Tổng thời gian giữa một 'disconnect' và 'connect' kế tiếp."""
    total, down_at = 0.0, None
    for _, r in meta.sort_values("ts").iterrows():
        m = r["meta"] if isinstance(r["meta"], dict) else {}
        e = m.get("event")
        if e == "disconnect":
            down_at = r["ts"]
        elif e == "connect" and down_at is not None:
            total += (r["ts"] - down_at) / 1000
            down_at = None
    return total


def session_table(ev: pd.DataFrame, criteria: dict | None = None) -> pd.DataFrame:
    criteria = criteria or {}
    out = []
    for sid, g in ev.groupby("session_id", sort=False):
        body = g[g["type"] != "_meta"]
        if body.empty:
            continue
        meta = g[g["type"] == "_meta"]
        start, end = int(body["ts"].min()), int(body["ts"].max())
        dur_min = (end - start) / 60_000
        comments = body[body["type"] == "comment"]
        viewers = pd.to_numeric(body.loc[body["type"] == "viewer", "total"], errors="coerce").dropna()
        from_start = any(isinstance(m, dict) and m.get("was_offline_before") for m in meta["meta"])
        # thiếu capture_stop = recorder bị tắt đột ngột (mất điện...) -> xem data/raw/_incidents.jsonl
        ended_clean = any(isinstance(m, dict) and m.get("event") == "capture_stop" for m in meta["meta"])
        # lượt thu (cột batch của channels.csv lúc mở phiên); phiên trước 02/10/2026 không có -> None
        batch = next((m.get("batch") for m in meta["meta"]
                      if isinstance(m, dict) and m.get("event") == "capture_start" and m.get("batch")), None)
        disc = _disconnected_seconds(meta)
        out.append({
            "session_id": sid,
            "channel": g["channel"].iloc[0],
            "start_ms": start,
            "end_ms": end,
            "duration_min": round(dur_min, 2),
            "n_comments_raw": int(len(comments)),
            "n_commenters": int(comments["user"].nunique()),
            "peak_viewers": float(viewers.max()) if len(viewers) else np.nan,
            "mean_viewers": float(viewers.mean()) if len(viewers) else np.nan,
            "captured_from_start": bool(from_start),
            "ended_clean": bool(ended_clean),
            "batch": batch,
            "disconnected_share": round(disc / max(dur_min * 60, 1), 4),
        })
    st = pd.DataFrame(out)
    if st.empty:
        return st
    st["valid"] = (
        (st["duration_min"] >= criteria.get("min_duration_min", 30))
        & (st["disconnected_share"] <= criteria.get("max_disconnected_share", 0.10))
        & (st["captured_from_start"] | (not criteria.get("require_from_start", True)))
    )
    return st


def save(df: pd.DataFrame, path: str | Path) -> Path:
    """Parquet nếu có pyarrow, ngược lại CSV (để test chạy được ở mọi nơi)."""
    path = resolve(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path.with_suffix(".parquet"), index=False)
        return path.with_suffix(".parquet")
    except (ImportError, ValueError):
        df2 = df.copy()
        if "meta" in df2.columns:
            df2["meta"] = df2["meta"].map(lambda m: json.dumps(m, ensure_ascii=False) if isinstance(m, dict) else m)
        df2.to_csv(path.with_suffix(".csv"), index=False)
        return path.with_suffix(".csv")


def load(path: str | Path) -> pd.DataFrame:
    path = resolve(path)
    pq, csv = path.with_suffix(".parquet"), path.with_suffix(".csv")
    if pq.exists():
        return pd.read_parquet(pq)
    return pd.read_csv(csv)


def main() -> None:
    ap = argparse.ArgumentParser(description="Đọc dữ liệu thô, dựng phiên, ghi events + sessions.")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/interim")
    ap.add_argument("--config", default="configs/capture.yaml")
    a = ap.parse_args()
    cfg = load_yaml(a.config)
    ev = sessionize(load_events(iter_raw_files(a.raw)), cfg.get("session", {}).get("gap_minutes", 15))
    st = session_table(ev, cfg.get("session_criteria", {}))
    p1 = save(ev, Path(a.out) / "events")
    p2 = save(st, Path(a.out) / "sessions")
    print(f"events: {len(ev):,} dòng -> {p1}\nsessions: {len(st)} phiên ({int(st['valid'].sum()) if len(st) else 0} hợp lệ) -> {p2}")
    if ev.attrs.get("bad_lines"):
        print(f"cảnh báo: bỏ qua {ev.attrs['bad_lines']} dòng JSON hỏng")


if __name__ == "__main__":
    main()

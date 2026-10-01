"""Tình trạng thu thập hôm nay (giờ Việt Nam): kênh | phiên | số sự kiện | phút mất kết nối | nhịp tim cuối.

- Đọc data/raw/_heartbeat.json (scheduler ghi mỗi phút) và các file JSONL có sự kiện trong ngày hôm nay.
  Writer chia thư mục theo ngày UTC, nên "hôm nay" giờ Việt Nam có thể nằm ở 2 thư mục.
- Cảnh báo (mã thoát 1) nếu nhịp tim cũ hơn --stale-min phút: máy/WSL đã ngủ hoặc scheduler chết.
- Phút mất kết nối: tổng các khoảng disconnect -> connect; nếu phiên chưa dừng mà đang mất kết nối,
  tính đến hiện tại.
- Chỉ in tên kênh (máy cục bộ), không in user hay nội dung bình luận.

Chạy:  python scripts/capture_status.py            (một lần)
       python scripts/capture_status.py --watch 30 (làm mới mỗi 30 giây)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

VN_TZ = timezone(timedelta(hours=7))
COLUMNS = ["kênh", "phiên", "sự kiện", "bình luận", "người xem", "phút mất kết nối", "nối lại",
           "nhịp tim cuối", "trạng thái"]


def read_heartbeat(raw_dir: Path) -> dict | None:
    p = Path(raw_dir) / "_heartbeat.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def incidents_today(raw_dir: Path, now: datetime) -> list[dict]:
    """Các lần tắt đột ngột được phát hiện hôm nay (giờ VN), từ data/raw/_incidents.jsonl."""
    start_ms, end_ms = local_day_bounds(now)
    out = []
    try:
        with open(Path(raw_dir) / "_incidents.jsonl", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if start_ms <= int(r.get("detected_at", 0)) < end_ms:
                    out.append(r)
    except OSError:
        pass
    return out


def heartbeat_age_s(hb: dict | None, now: datetime) -> float | None:
    if not hb or "ts" not in hb:
        return None
    return now.timestamp() - float(hb["ts"])


def local_day_bounds(now: datetime) -> tuple[int, int]:
    """[đầu ngày, đầu ngày mai) theo giờ Việt Nam, tính bằng ms."""
    start = now.astimezone(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)


def today_files(raw_dir: Path, now: datetime) -> list[Path]:
    """Các file JSONL trong những thư mục ngày UTC giao với hôm nay (giờ Việt Nam)."""
    start_ms, end_ms = local_day_bounds(now)
    days = {datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") for ms in (start_ms, end_ms - 1)}
    files: list[Path] = []
    for d in sorted(days):
        files += sorted((Path(raw_dir) / d).rglob("*.jsonl"))
    return files


def load_rows(files: list[Path]) -> pd.DataFrame:
    rows = []
    for p in files:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # dòng cuối bị cắt khi đang ghi
    df = pd.DataFrame(rows)
    for c in ("type", "channel", "session_hint", "ts", "meta"):
        if c not in df.columns:
            df[c] = None
    return df


def disconnected_seconds(metas: list[dict], now_ms: int) -> tuple[float, int]:
    """(giây mất kết nối, số lần nối lại) từ chuỗi _meta (mỗi phần tử có ts và meta.event).

    Khoảng mất = disconnect -> connect kế tiếp. Nếu sau disconnect là capture_stop thì không tính
    (phiên đã kết thúc). Nếu chưa có gì sau disconnect: tính đến now_ms (đang mất kết nối).
    """
    total, down_at, n_connect = 0.0, None, 0
    for m in sorted(metas, key=lambda r: r["ts"]):
        ev = (m.get("meta") or {}).get("event")
        if ev == "connect":
            n_connect += 1
            if down_at is not None:
                total += (m["ts"] - down_at) / 1000
                down_at = None
        elif ev == "disconnect":
            down_at = m["ts"]
        elif ev == "capture_stop":
            down_at = None
    if down_at is not None:
        total += max(now_ms - down_at, 0) / 1000
    return total, max(n_connect - 1, 0)


def session_table(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Một dòng mỗi phiên có ít nhất một dòng ghi trong hôm nay (giờ Việt Nam)."""
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    start_ms, end_ms = local_day_bounds(now)
    now_ms = int(now.timestamp() * 1000)
    df = df.dropna(subset=["ts", "session_hint"]).copy()
    df["ts"] = df["ts"].astype("int64")
    out = []
    for (ch, sess), g in df.groupby(["channel", "session_hint"], sort=True):
        if not ((g["ts"] >= start_ms) & (g["ts"] < end_ms)).any():
            continue
        g = g.sort_values("ts", kind="stable")
        body = g[g["type"] != "_meta"]
        metas = g[g["type"] == "_meta"][["ts", "meta"]].to_dict("records")
        events = {(m.get("meta") or {}).get("event") for m in metas}
        down_s, n_reconnect = disconnected_seconds(metas, now_ms)
        viewers = pd.to_numeric(body.loc[body["type"] == "viewer", "total"], errors="coerce").dropna() \
            if "total" in body else pd.Series(dtype=float)
        last_ms = int(g["ts"].max())
        out.append({
            "kênh": ch,
            "phiên": str(sess).rsplit("_", 1)[-1],
            "sự kiện": int(len(body)),
            "bình luận": int((body["type"] == "comment").sum()),
            "người xem": int(viewers.iloc[-1]) if len(viewers) else None,
            "phút mất kết nối": round(down_s / 60, 1),
            "nối lại": n_reconnect,
            "nhịp tim cuối": datetime.fromtimestamp(last_ms / 1000, VN_TZ).strftime("%H:%M:%S"),
            "trạng thái": "đã dừng" if "capture_stop" in events else "đang ghi",
        })
    table = pd.DataFrame(out, columns=COLUMNS)
    table["người xem"] = table["người xem"].astype("Int64")  # số nguyên, ô trống hiện <NA> thay vì 370.0
    return table


def render(table: pd.DataFrame, hb: dict | None, now: datetime, stale_min: float,
           backup: dict | None = None, incidents: list[dict] | None = None,
           backup_stale_min: float = 60) -> tuple[str, bool]:
    """(văn bản, nhịp tim có cũ hay không). Sao lưu trễ / sự cố chỉ in cảnh báo, không đổi mã thoát."""
    lines = [f"Thu thập hôm nay — {now.astimezone(VN_TZ):%Y-%m-%d %H:%M:%S} (giờ VN)"]
    age = heartbeat_age_s(hb, now)
    stale = age is None or age > stale_min * 60
    if age is None:
        lines.append("CẢNH BÁO: không đọc được _heartbeat.json — scheduler chưa chạy?")
    else:
        hb_time = datetime.fromtimestamp(float(hb["ts"]), VN_TZ).strftime("%H:%M:%S")
        active = ", ".join(hb.get("active") or []) or "không"
        lines.append(f"Nhịp tim scheduler: {hb_time} ({age / 60:.1f} phút trước) | đang ghi: {active}")
        if stale:
            lines.append(f"CẢNH BÁO: nhịp tim cũ hơn {stale_min:g} phút — máy/WSL đã ngủ hoặc scheduler đã dừng.")
    if hb and "sessions_today" in hb:
        cap = hb.get("quota")
        lines.append(f"Phiên hôm nay: {hb['sessions_today']}" + (f"/{cap}" if cap is not None else " (không giới hạn)"))
    if backup is None:
        lines.append("CẢNH BÁO: chưa có bản sao lưu nào (bash scripts/backup_data.sh).")
    else:
        b_age = (now.timestamp() - float(backup["ts"])) / 60
        lines.append(f"Sao lưu gần nhất: {b_age:.0f} phút trước -> {backup.get('dest')} ({backup.get('size')})")
        if b_age > backup_stale_min:
            lines.append(f"CẢNH BÁO: sao lưu trễ hơn {backup_stale_min:g} phút — kiểm tra livesp-backup.timer.")
    for inc in incidents or []:
        t = datetime.fromtimestamp(inc["last_heartbeat"] / 1000, VN_TZ).strftime("%H:%M")
        lines.append(f"SỰ CỐ: tắt đột ngột sau {t}, gián đoạn ~{inc.get('downtime_min')} phút, "
                     f"{len(inc.get('unclosed_sessions') or [])} phiên chưa đóng.")
    lines.append("")
    lines.append("Chưa có phiên nào hôm nay." if table.empty else table.to_string(index=False))
    return "\n".join(lines), stale


def main() -> int:
    ap = argparse.ArgumentParser(description="Tình trạng thu thập hôm nay.")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--stale-min", type=float, default=5.0)
    ap.add_argument("--watch", type=float, default=0, help="làm mới mỗi N giây (0 = chạy một lần)")
    a = ap.parse_args()
    raw = Path(a.raw)
    while True:
        now = datetime.now(timezone.utc)
        text, stale = render(session_table(load_rows(today_files(raw, now)), now), read_heartbeat(raw), now,
                             a.stale_min, backup=read_json(raw / "_last_backup.json"),
                             incidents=incidents_today(raw, now))
        if a.watch:
            print("\033[2J\033[H", end="")
        print(text, flush=True)
        if not a.watch:
            return 1 if stale else 0
        time.sleep(a.watch)


if __name__ == "__main__":
    sys.exit(main())

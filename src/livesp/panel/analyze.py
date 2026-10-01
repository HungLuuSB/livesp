"""Study 2: dựng bảng theo phút và ước lượng mô hình chính + chiều ngược + đa vũ trụ.

Chặn toàn vẹn nghiên cứu: trên dữ liệu kiểm định (11–12/2026) chỉ chạy khi configs/FROZEN đã có
filters.yaml và panel.yaml (tức đã đăng ký trước trên OSF). Dữ liệu phát triển: thêm --dev.

Chạy: python -m livesp.panel.analyze --events data/interim/events --comments data/processed/comments_pred \
          --sessions data/interim/sessions --dev
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ..config import is_frozen, load_yaml, resolve
from ..data.ingest import load, save
from .fe import fe_ols, reverse_direction
from .responsiveness import responsiveness
from .windows import add_lags, build_panel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="data/interim/events")
    ap.add_argument("--comments", default="data/processed/comments_pred")
    ap.add_argument("--sessions", default="data/interim/sessions")
    ap.add_argument("--config", default="configs/panel.yaml")
    ap.add_argument("--out", default="results/panel")
    ap.add_argument("--dev", action="store_true", help="dữ liệu phát triển: bỏ qua kiểm tra đóng băng")
    a = ap.parse_args()
    if not a.dev and not (is_frozen("panel.yaml") and is_frozen("filters.yaml")):
        raise SystemExit("Chưa đóng băng panel.yaml và filters.yaml (configs/FROZEN). Đăng ký OSF trước, hoặc thêm --dev.")
    cfg = load_yaml(a.config)
    ev, com, st = load(a.events), load(a.comments), load(a.sessions)
    valid = set(st.loc[st["valid"].astype(bool), "session_id"])
    ev, com = ev[ev["session_id"].isin(valid)], com[com["session_id"].isin(valid)]
    resp = responsiveness(com) if cfg.get("use_resp", True) else None
    panel = build_panel(ev, com, cfg.get("window_s", 60), resp=resp, sessions=st)
    sp_cols = cfg["sp_vars"]
    panel = add_lags(panel, sp_cols, cfg.get("lags", 3))
    out = resolve(a.out)
    out.mkdir(parents=True, exist_ok=True)
    save(panel, out / "panel")
    rows = []
    for y in cfg["outcomes"]:
        base_y = y.replace("y_", "n_") if y != "y_dlog_viewers" else "log_viewers"
        X = sp_cols + [f"{c}_l{k}" for c in sp_cols for k in range(1, cfg.get("lags", 3) + 1)] + [base_y] + cfg["controls"]
        r = fe_ols(panel, y, X, time_fe="minute_bin").assign(outcome=y, model="main")
        rows.append(r)
        for sp in sp_cols:
            rr = reverse_direction(panel, sp, base_y, cfg["controls"]).assign(outcome=y, model=f"reverse:{sp}")
            rows.append(rr)
    import pandas as pd

    res = pd.concat(rows)
    res.to_csv(out / "fe_results.csv", index=False)
    print(res[res["term"].isin(sp_cols)].to_string(index=False))
    print(f"-> {out}/fe_results.csv (đa vũ trụ: xem panel/fe.py::multiverse và docs/CLAUDE_CODE_TASKS.md)")


if __name__ == "__main__":
    main()

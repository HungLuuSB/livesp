"""Danh sách kênh configs/channels.csv: đọc, quy đổi số follower, kiểm tra theo khung mẫu, bảng ô.

Cột: channel, category_group, followers, followers_date, follower_tier, enabled, batch (tùy chọn), note.
Khung mẫu (ngành × tầng follower, số kênh mỗi ô) lấy từ configs/capture.yaml -> sampling_frame.

- followers nhận "472K", "1.1M", "3,249", "472,1 N", "1,1 Tr" (cách TikTok tiếng Việt hiển thị) -> số nguyên.
- follower_tier suy ra từ followers (cận dưới tính vào tầng); "..." hoặc trống = chưa điền.
- Dùng bởi scripts/validate_channels.py (kiểm tra, --fix) và scheduler (đọc lại danh sách định kỳ).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

import pandas as pd

COLUMNS = ["channel", "category_group", "followers", "followers_date", "follower_tier", "enabled", "batch", "note"]
REQUIRED = ["channel", "category_group", "followers", "followers_date", "follower_tier", "enabled"]
# Handle TikTok: chữ, số, gạch dưới, dấu chấm; 2–24 ký tự.
HANDLE_RE = re.compile(r"^[A-Za-z0-9_.]{2,24}$")
_SUFFIX = {"": 1, "k": 1_000, "n": 1_000, "nghìn": 1_000, "ngàn": 1_000,
           "m": 1_000_000, "tr": 1_000_000, "triệu": 1_000_000, "b": 1_000_000_000, "tỷ": 1_000_000_000}
_FOLLOWERS_RE = re.compile(r"^([0-9][0-9.,]*)\s*([a-zA-Zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]*)$")
BLANK_TIER = {"", "...", "…", "?"}


def parse_followers(value: object) -> int | None:
    """'472K' -> 472000; '1.1M' -> 1100000; '3,249' -> 3249; '472,1 N' -> 472100; '1,1 Tr' -> 1100000."""
    s = str(value or "").strip().lower().replace(" ", " ")
    m = _FOLLOWERS_RE.match(s)
    if not m or m.group(2) not in _SUFFIX:
        return None
    num, mult = m.group(1), _SUFFIX[m.group(2)]
    if mult == 1:
        # số nguyên đầy đủ: dấu chấm/phẩy là phân cách hàng nghìn ("3,249", "1.100.000")
        digits = num.replace(",", "").replace(".", "")
        return int(digits) if digits.isdigit() else None
    # có hậu tố: dấu phẩy là dấu thập phân kiểu Việt ("472,1 N")
    num = num.replace(",", ".")
    if num.count(".") > 1:
        return None
    try:
        return int(round(float(num) * mult))
    except ValueError:
        return None


def tier_for(n: int, tiers: dict) -> str | None:
    """Tầng chứa n: lo <= n < hi (hi None = không giới hạn trên)."""
    for name, (lo, hi) in tiers.items():
        if n >= lo and (hi is None or n < hi):
            return name
    return None


def read_rows(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k is not None} for r in csv.DictReader(f)]


def clean_handle(ch: str) -> str:
    return ch.strip().lstrip("@").strip()


def enabled(row: dict) -> bool:
    return str(row.get("enabled", "1")).strip().lower() in ("1", "true")


def capture_rows(rows: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """Những gì scheduler cần: {handle: row} cho các kênh bật và handle hợp lệ; kèm cảnh báo cho dòng bị bỏ."""
    out, warn = {}, []
    for i, r in enumerate(rows, start=2):
        if not enabled(r):
            continue
        h = clean_handle(r.get("channel", ""))
        if not HANDLE_RE.match(h):
            warn.append(f"dòng {i}: tên kênh không hợp lệ {h!r}, bỏ qua")
        elif h.lower() in {k.lower() for k in out}:
            warn.append(f"dòng {i}: kênh {h} bị trùng, bỏ qua")
        else:
            out[h] = r
    return out, warn


def validate(rows: list[dict], frame: dict) -> tuple[list[str], list[str], list[dict]]:
    """(lỗi, cảnh báo, các dòng đã chuẩn hóa). Chuẩn hóa = followers thành số nguyên, follower_tier suy từ followers;
    tên kênh và ngành KHÔNG bao giờ bị sửa. Lỗi chỉ còn lại những gì --fix không tự sửa được."""
    errors, warnings, fixed = [], [], []
    groups, tiers = set(frame["category_groups"]), frame["follower_tiers"]
    if rows:
        missing = [c for c in REQUIRED if c not in rows[0]]
        if missing:
            return [f"thiếu cột: {', '.join(missing)}"], [], rows
    seen: dict[str, int] = {}
    for i, r in enumerate(rows, start=2):  # dòng 1 là tiêu đề
        r = dict(r)
        raw = r.get("channel", "")
        if "@" in raw:
            errors.append(f"dòng {i}: tên kênh có '@' ({raw})")
        h = clean_handle(raw)
        if not h:
            errors.append(f"dòng {i}: thiếu tên kênh")
        elif not HANDLE_RE.match(h):
            errors.append(f"dòng {i}: tên kênh không hợp lệ ({h}) — chỉ chữ, số, '_' và '.', 2–24 ký tự")
        elif h.lower() in seen:
            errors.append(f"dòng {i}: trùng kênh {h} (đã có ở dòng {seen[h.lower()]})")
        else:
            seen[h.lower()] = i
        if r.get("category_group") not in groups:
            errors.append(f"dòng {i}: ngành '{r.get('category_group')}' không có trong khung ({', '.join(sorted(groups))})")
        n = parse_followers(r.get("followers"))
        if n is None:
            errors.append(f"dòng {i}: không đọc được followers '{r.get('followers')}'")
        else:
            r["followers"] = str(n)
            t = tier_for(n, tiers)
            given = r.get("follower_tier", "").strip()
            if given not in BLANK_TIER and given != t:
                warnings.append(f"dòng {i}: follower_tier '{given}' không khớp {n:,} followers -> {t}")
            r["follower_tier"] = t
        try:
            date.fromisoformat(r.get("followers_date", ""))
        except ValueError:
            errors.append(f"dòng {i}: followers_date '{r.get('followers_date')}' không phải ngày YYYY-MM-DD")
        if str(r.get("enabled", "")).strip() not in ("0", "1"):
            errors.append(f"dòng {i}: enabled phải là 0 hoặc 1 (đang là '{r.get('enabled')}')")
        if "batch" in r and not r.get("batch"):
            warnings.append(f"dòng {i}: thiếu batch")
        fixed.append(r)
    return errors, warnings, fixed


def needs_fix(rows: list[dict], fixed: list[dict]) -> bool:
    return any(a.get("followers") != b.get("followers") or a.get("follower_tier") != b.get("follower_tier")
               for a, b in zip(rows, fixed))


def grid(rows: list[dict], frame: dict) -> pd.DataFrame:
    """Số kênh ĐANG BẬT mỗi ô (ngành × tầng), đúng thứ tự trong khung; dùng follower_tier đã chuẩn hóa."""
    cats, tiers = list(frame["category_groups"]), list(frame["follower_tiers"])
    counts = pd.DataFrame(0, index=cats, columns=tiers)
    for r in rows:
        if enabled(r) and r.get("category_group") in cats and r.get("follower_tier") in tiers:
            counts.loc[r["category_group"], r["follower_tier"]] += 1
    return counts


def render_grid(counts: pd.DataFrame, per_cell: tuple[int, int]) -> tuple[str, int]:
    """(bảng văn bản, số ô chưa đạt). Ô: 'n' nếu đạt, 'n (thiếu k)' / 'n (thừa k)' nếu không."""
    lo, hi = per_cell
    cells = counts.map(lambda n: str(n) if lo <= n <= hi else (f"{n} (thiếu {lo - n})" if n < lo else f"{n} (thừa {n - hi})"))
    bad = int(((counts < lo) | (counts > hi)).to_numpy().sum())
    total, n_cells = int(counts.to_numpy().sum()), counts.size
    text = cells.to_string() + (f"\n\nTổng: {total} kênh đang bật / mục tiêu {n_cells * lo}–{n_cells * hi} "
                                f"({n_cells} ô × {lo}–{hi}); ô chưa đạt: {bad}/{n_cells}")
    return text, bad


def to_csv_text(rows: list[dict]) -> str:
    cols = [c for c in COLUMNS if any(c in r for r in rows)] or COLUMNS
    extra = [c for r in rows for c in r if c not in cols]
    cols += list(dict.fromkeys(extra))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()

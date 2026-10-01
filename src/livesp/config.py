"""Đọc cấu hình YAML và biến môi trường (.env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_dotenv(path: str | Path = ROOT / ".env") -> None:
    """Nạp .env đơn giản (KEY=VALUE), không ghi đè biến đã có trong môi trường."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def is_frozen(name: str) -> bool:
    """Một cấu hình được coi là đóng băng nếu tên nó nằm trong configs/FROZEN.

    Dùng để chặn việc sửa quy tắc lọc/đặc tả mô hình sau khi đã đăng ký trước.
    """
    frozen = ROOT / "configs" / "FROZEN"
    if not frozen.exists():
        return False
    names = {ln.strip() for ln in frozen.read_text(encoding="utf-8").splitlines() if ln.strip()}
    return name in names

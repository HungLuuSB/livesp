"""Chuẩn hóa teencode/viết tắt: ba mức để so sánh trong thí nghiệm.

naive      : thay mọi token khớp từ điển, không xét ngữ cảnh (gần với cách của khóa luận)
guarded    : như naive, nhưng (1) giữ nguyên từ vay mượn (ship, sale), (2) các khóa mơ hồ chỉ
             được thay khi một luật ngữ cảnh khớp, còn không thì GIỮ NGUYÊN
contextual : móc nối tới một bộ chuẩn hóa theo ngữ cảnh bên ngoài (ViSoLex, seq2seq, LLM)

Các ví dụ mơ hồ có thật trong live bán hàng:
    "99 k"        k = nghìn, không phải "không"
    "màu hong"    hong = hồng, không phải "không"
    "đôi dep"     dep = dép, không phải "đẹp"
    "size m"      m = size M, không phải "mình"
    "cảm ơn bn"   bn = bạn, không phải "bao nhiêu"
"""
from __future__ import annotations

import re
from typing import Callable

# Từ điển nền: 49 mục của khóa luận (Phụ lục C) + một số mục hay gặp.
BASE_DICT: dict[str, str] = {
    "ko": "không", "k": "không", "kh": "không", "hok": "không", "hong": "không", "hông": "không",
    "dc": "được", "đc": "được", "dk": "được", "đk": "được",
    "bt": "bình thường", "bth": "bình thường",
    "ib": "nhắn tin", "inbox": "nhắn tin", "nt": "nhắn tin",
    "gh": "giỏ hàng", "stk": "số tài khoản", "sp": "sản phẩm", "sz": "size",
    "ship": "giao hàng", "sale": "giảm giá",
    "mn": "mọi người", "mng": "mọi người", "ae": "anh em", "ce": "chị em",
    "ad": "admin", "sh": "shop",
    "z": "vậy", "v": "vậy", "r": "rồi", "rui": "rồi", "roi": "rồi",
    "oke": "ok", "okie": "ok", "oki": "ok",
    "trc": "trước", "ntn": "như thế nào", "mik": "mình", "mk": "mình", "m": "mình",
    "bn": "bao nhiêu", "nhiu": "nhiêu", "tks": "cảm ơn", "thanks": "cảm ơn",
    "cx": "cũng", "vs": "với", "wa": "quá", "qa": "quá", "xiu": "xíu", "iu": "yêu",
    "xink": "xinh", "dep": "đẹp",
    "c": "chị", "e": "em", "j": "gì", "lm": "làm",
    "dt": "điện thoại", "đt": "điện thoại", "ng": "người", "vc": "vợ chồng",
}

# Từ vay mượn / thuật ngữ miền: KHÔNG dịch ở chế độ guarded (dịch làm mất "chất" livestream).
LOANWORDS = {"ship", "sale", "sz", "ad", "sh", "inbox", "ib", "thanks", "oke", "okie", "oki"}

# Các khóa mơ hồ: chỉ thay khi luật ngữ cảnh trả về một giá trị.
_NUM_RE = re.compile(r"^\d+([.,]\d+)?$")
_SIZE_WORDS = {"size", "sz", "sai", "sài", "sìze", "<size>"}
_PRAISE_NEXT = {"qua", "quá", "qa", "wa", "lam", "lắm", "ghe", "ghê", "the", "thế", "xỉu", "xiu", "vl", "vãi", "z", "v", "vậy", "ha", "hà"}
_SANDAL_PREV = {"đôi", "doi", "dôi", "mang", "dép", "size", "sz"}
_SANDAL_NEXT = {"tổ", "to", "lê", "le", "quai", "sục", "suc", "kẹp", "kep", "da", "nữ", "nam", "bánh"}
_COLOR_PREV = {"màu", "mau", "áo", "ao", "váy", "vay", "son"}
_COLOR_NEXT = {"nhạt", "nhat", "đậm", "dam", "pastel", "phấn", "phan", "cánh", "canh", "sen"}
_VOC_NEXT = {"ơi", "oi", "ui", "iu", "ạ", "a"}
_THANK_PREV = {"ơn", "on", "của", "cua", "với", "voi"}


def _ctx_k(prev: str, nxt: str) -> str | None:
    if _NUM_RE.match(prev):  # "99 k" -> nghìn
        return "nghìn"
    return "không"


def _ctx_dep(prev: str, nxt: str) -> str | None:
    if prev in _SANDAL_PREV or nxt in _SANDAL_NEXT:
        return "dép"
    if nxt in _PRAISE_NEXT or nxt == "":
        return "đẹp"
    return None


def _ctx_hong(prev: str, nxt: str) -> str | None:
    if prev in _COLOR_PREV or nxt in _COLOR_NEXT:
        return "hồng"
    return "không"


def _ctx_bn(prev: str, nxt: str) -> str | None:
    if prev in {"giá", "gia", "hết", "het", "là", "la"} or nxt in {"tiền", "tien", "k", "ạ", "a", "?", "vậy", "v", "z", "cái", "cai", "1", "2"}:
        return "bao nhiêu"
    if prev in _THANK_PREV or nxt in _VOC_NEXT:
        return "bạn"
    return None


def _ctx_gh(prev: str, nxt: str) -> str | None:
    if prev in {"vào", "vao", "trong", "bỏ", "bo", "thêm", "them", "xem"}:
        return "giỏ hàng"
    if nxt in {"nhanh", "chậm", "cham", "tận", "tan", "mấy", "may", "bao", "hôm", "hom"}:
        return "giao hàng"
    return None


def _ctx_dk(prev: str, nxt: str) -> str | None:
    if nxt in {"kênh", "kenh", "tv", "thành", "thanh", "kênhh"}:
        return "đăng ký"
    return "được"


def _ctx_m(prev: str, nxt: str) -> str | None:
    if prev in _SIZE_WORDS:
        return None  # giữ "m" là size
    return "mình"


def _ctx_c(prev: str, nxt: str) -> str | None:
    if nxt in _VOC_NEXT or prev in {"dạ", "da", "ơn", "on"}:
        return "chị"
    return None


AMBIGUOUS: dict[str, Callable[[str, str], str | None]] = {
    "k": _ctx_k, "dep": _ctx_dep, "hong": _ctx_hong, "hông": _ctx_hong, "bn": _ctx_bn,
    "gh": _ctx_gh, "dk": _ctx_dk, "đk": _ctx_dk, "m": _ctx_m, "c": _ctx_c,
}

_TOKEN_RE = re.compile(r"<[^<>\s]+>|:[\w_]+:|@\w+|\w+|[^\w\s]", re.UNICODE)


def _tokens(s: str) -> list[str]:
    return _TOKEN_RE.findall(s)


def _rejoin(tokens: list[str]) -> str:
    out = ""
    for t in tokens:
        if out and not re.match(r"^[,.!?;:)]$", t):
            out += " "
        out += t
    return out


def normalize(s: str, mode: str = "none", dictionary: dict[str, str] | None = None) -> str:
    """Chuẩn hóa teencode theo mức `mode`. Chỉ các token khớp từ điển mới đổi; phần còn lại giữ nguyên."""
    if mode in (None, "none", False):
        return s
    if mode == "contextual":
        return contextual_normalize([s])[0]
    d = dictionary or BASE_DICT
    toks = _tokens(s)
    low = [t.lower() for t in toks]
    changed = False
    out = list(toks)
    for i, t in enumerate(low):
        if t not in d:
            continue
        if mode == "naive":
            out[i] = d[t]
            changed = True
            continue
        if mode != "guarded":
            raise ValueError(f"teencode mode không hợp lệ: {mode}")
        if t in LOANWORDS:
            continue
        prev = low[i - 1] if i > 0 else ""
        nxt = low[i + 1] if i + 1 < len(low) else ""
        if t in AMBIGUOUS:
            rep = AMBIGUOUS[t](prev, nxt)
            if rep is not None:
                out[i] = rep
                changed = True
        else:
            out[i] = d[t]
            changed = True
    return _rejoin(out) if changed else s


_CONTEXTUAL_BACKEND: Callable[[list[str]], list[str]] | None = None


def register_contextual_backend(fn: Callable[[list[str]], list[str]]) -> None:
    """Đăng ký một bộ chuẩn hóa theo ngữ cảnh (ViSoLex, mô hình seq2seq, LLM...).

    Hàm nhận list văn bản, trả list văn bản cùng độ dài. Xem docs/CLAUDE_CODE_TASKS.md (Task 9).
    """
    global _CONTEXTUAL_BACKEND
    _CONTEXTUAL_BACKEND = fn


def contextual_normalize(texts: list[str]) -> list[str]:
    if _CONTEXTUAL_BACKEND is None:
        raise NotImplementedError(
            "Chưa đăng ký bộ chuẩn hóa theo ngữ cảnh. Gọi register_contextual_backend(fn) "
            "hoặc bỏ điều kiện teencode=contextual khỏi configs/preprocess_conditions.yaml."
        )
    out = _CONTEXTUAL_BACKEND(texts)
    if len(out) != len(texts):
        raise ValueError("Bộ chuẩn hóa theo ngữ cảnh trả về sai số lượng văn bản.")
    return out


def teencode_tokens(s: str, dictionary: dict[str, str] | None = None) -> list[str]:
    """Các token teencode xuất hiện trong câu (dùng cho lát cắt đánh giá)."""
    d = dictionary or BASE_DICT
    return [t for t in (x.lower() for x in _tokens(s)) if t in d]

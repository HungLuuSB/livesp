"""Các bước tiền xử lý dạng hàm thuần str -> str.

Chia theo bản chất (xem PROPOSAL, Study 1):
    Mã hóa              : unicode_nfc, tone_placement        -> gần như không mất thông tin
    Hình thức mang nghĩa: elongation, emoji, lowercase      -> có thể xóa tín hiệu cảm xúc
    Giải nghĩa từ vựng  : placeholders (+ teencode.py)      -> cần ngữ cảnh để làm đúng

Mọi hàm đều nhận `mode` để thí nghiệm ablation bật/tắt từng mức một.
"""
from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------- điều khiển
_CONTROL_RE = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff]")
_WS_RE = re.compile(r"\s+")


def strip_control(s: str) -> str:
    """Luôn chạy (không phải một yếu tố thí nghiệm): bỏ ký tự điều khiển/zero-width, gộp khoảng trắng."""
    s = _CONTROL_RE.sub("", s or "")
    return _WS_RE.sub(" ", s).strip()


# --------------------------------------------------------------------------- Unicode
def unicode_nfc(s: str, mode: str = "nfc") -> str:
    if mode in (None, "none", False):
        return s
    return unicodedata.normalize("NFC", s)


# --------------------------------------------------------------------------- vị trí dấu thanh
# Dấu thanh (tách khỏi dấu mũ/móc/trăng): huyền, sắc, hỏi, ngã, nặng.
_TONES = {"\u0300", "\u0301", "\u0309", "\u0303", "\u0323"}
_CONS = "bcdđghklmnpqrstvx"
_WORD_RE = re.compile(r"\w+", re.UNICODE)
# Nhóm vần mà hai kiểu đặt dấu khác nhau khi KHÔNG có phụ âm cuối: oa, oe, uy (hòa/hoà, khỏe/khoẻ, thủy/thuỷ).
_PAIRS = {("o", "a"), ("o", "e"), ("u", "y")}


def _strip_tone(ch: str) -> tuple[str, str | None]:
    d = unicodedata.normalize("NFD", ch)
    tone = next((c for c in d if c in _TONES), None)
    base = unicodedata.normalize("NFC", "".join(c for c in d if c not in _TONES))
    return base, tone


def _move_tone_in_word(word: str, style: str) -> str:
    chars = list(unicodedata.normalize("NFC", word))
    bases, tones = zip(*(_strip_tone(c) for c in chars)) if chars else ((), ())
    base_lower = "".join(bases).lower()
    tone_positions = [i for i, t in enumerate(tones) if t]
    if len(tone_positions) != 1:
        return word
    # Tách phụ âm đầu (chữ cái thường, không dấu).
    i = 0
    while i < len(base_lower) and base_lower[i] in _CONS:
        i += 1
    onset, rhyme = base_lower[:i], base_lower[i:]
    if len(rhyme) != 2 or (rhyme[0], rhyme[1]) not in _PAIRS:
        return word
    if rhyme == "uy" and onset.endswith("q"):  # "quý": u thuộc phụ âm "qu"
        return word
    first, second = i, i + 1
    tpos = tone_positions[0]
    tone = tones[tpos]
    target = second if style == "new" else first
    if tpos == target or tpos not in (first, second):
        return word
    out = list(bases)
    out[target] = unicodedata.normalize("NFC", out[target] + tone)
    return "".join(out)


def tone_placement(s: str, mode: str = "new") -> str:
    """Chuẩn hóa vị trí dấu thanh cho vần oa/oe/uy không có phụ âm cuối.

    mode="new": hòa->hoà, khỏe->khoẻ, thủy->thuỷ ; mode="old": chiều ngược lại ; "none": giữ nguyên.
    Mục tiêu là NHẤT QUÁN, không phải "đúng" — hai kiểu đều hợp lệ trong thực tế.
    """
    if mode in (None, "none", False):
        return s
    return _WORD_RE.sub(lambda m: _move_tone_in_word(m.group(0), mode), s)


# --------------------------------------------------------------------------- ký tự kéo dài
_RUN3_RE = re.compile(r"(\w)\1{2,}", re.UNICODE)
ELONG_TOKEN = "<kéo_dài>"


def _base_letter(ch: str) -> str:
    return unicodedata.normalize("NFD", ch)[0].lower() if ch.isalpha() else ch


def _collapse_runs(word: str, keep: int) -> tuple[str, bool]:
    """Gộp các chuỗi >= 3 ký tự có CÙNG chữ cái gốc (bỏ dấu), vd 'quáaaa' -> 'quá', 'đẹppppp' -> 'đẹp'.

    Giữ lại ký tự mang nhiều dấu nhất trong chuỗi (để 'áaaa' -> 'á' chứ không phải 'a').
    """
    out, i, changed = [], 0, False
    while i < len(word):
        j = i
        while j + 1 < len(word) and word[j + 1].isalpha() and _base_letter(word[j + 1]) == _base_letter(word[i]):
            j += 1
        run = word[i : j + 1]
        if len(run) >= 3 and word[i].isalpha():
            best = max(run, key=lambda c: len(unicodedata.normalize("NFD", c)))
            out.append(best * keep if keep == 1 else best + run[-1] * (keep - 1))
            changed = True
        else:
            out.append(run)
        i = j + 1
    return "".join(out), changed


def elongation(s: str, mode: str = "keep") -> str:
    """Xử lý chuỗi ký tự lặp >= 3 lần (đẹppppp, quáaaa).

    keep     : giữ nguyên (tín hiệu cường độ cảm xúc)
    one      : rút về 1 ký tự (cách của khóa luận) -> mất tín hiệu
    two      : rút về 2 ký tự (giữ dấu vết nhấn mạnh, giảm độ thưa từ vựng)
    one_mark : rút về 1 ký tự + thêm token <kéo_dài> sau từ (giữ tín hiệu, bỏ độ thưa)
    """
    if mode in (None, "keep", "none", False):
        return s
    if mode not in ("one", "two", "one_mark"):
        raise ValueError(f"elongation mode không hợp lệ: {mode}")
    keep = 2 if mode == "two" else 1

    def fix(m: re.Match) -> str:
        w, changed = _collapse_runs(m.group(0), keep)
        return w + " " + ELONG_TOKEN if (changed and mode == "one_mark") else w

    return _WORD_RE.sub(fix, s)


def has_elongation(s: str) -> bool:
    return any(_collapse_runs(m.group(0), 1)[1] for m in _WORD_RE.finditer(s or ""))


# --------------------------------------------------------------------------- emoji
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # biểu tượng & hình
    "\U0001F600-\U0001F64F"  # mặt cười
    "\U0001F680-\U0001F6FF"  # giao thông
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"  # bổ sung
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"          # ký hiệu linh tinh
    "\u2700-\u27BF"          # dingbats
    "\u2764"
    "]"
    "[\uFE0F\u200D\U0001F3FB-\U0001F3FF]*",  # biến thể, ZWJ, màu da
    re.UNICODE,
)

# Bảng nhỏ các emoji hay gặp trong live bán hàng. Emoji không có trong bảng -> token chung.
EMOJI_VI = {
    "😍": "mắt_trái_tim", "🥰": "mặt_cười_trái_tim", "😘": "hôn_gió", "❤": "tim", "❤️": "tim",
    "💕": "hai_trái_tim", "💖": "tim_lấp_lánh", "💗": "tim_đập", "😂": "cười_ra_nước_mắt",
    "🤣": "cười_lăn", "😆": "cười_híp_mắt", "😁": "cười_nhe_răng", "😊": "mỉm_cười",
    "🙂": "cười_nhẹ", "😅": "cười_toát_mồ_hôi", "😭": "khóc_to", "😢": "khóc", "🥺": "năn_nỉ",
    "😡": "giận", "😤": "bực", "👍": "like", "👏": "vỗ_tay", "🙏": "cảm_ơn_chắp_tay",
    "🔥": "lửa", "💯": "điểm_100", "🎉": "chúc_mừng", "🌹": "hoa_hồng", "🌸": "hoa",
    "😱": "hoảng", "🤔": "suy_nghĩ", "😋": "ngon", "🤤": "thèm", "💪": "cơ_bắp",
    "🛒": "giỏ_hàng", "🎁": "quà", "✨": "lấp_lánh", "⭐": "sao", "🥳": "ăn_mừng", "😎": "ngầu",
}
EMOJI_EN = {
    "😍": "heart_eyes", "🥰": "smiling_face_with_hearts", "😘": "face_blowing_a_kiss", "❤": "red_heart",
    "❤️": "red_heart", "💕": "two_hearts", "💖": "sparkling_heart", "💗": "growing_heart",
    "😂": "face_with_tears_of_joy", "🤣": "rolling_on_the_floor_laughing", "😆": "grinning_squinting_face",
    "😁": "beaming_face", "😊": "smiling_face_with_smiling_eyes", "🙂": "slightly_smiling_face",
    "😅": "grinning_face_with_sweat", "😭": "loudly_crying_face", "😢": "crying_face", "🥺": "pleading_face",
    "😡": "enraged_face", "😤": "face_with_steam", "👍": "thumbs_up", "👏": "clapping_hands",
    "🙏": "folded_hands", "🔥": "fire", "💯": "hundred_points", "🎉": "party_popper", "🌹": "rose",
    "🌸": "cherry_blossom", "😱": "face_screaming", "🤔": "thinking_face", "😋": "face_savoring_food",
    "🤤": "drooling_face", "💪": "flexed_biceps", "🛒": "shopping_cart", "🎁": "wrapped_gift",
    "✨": "sparkles", "⭐": "star", "🥳": "partying_face", "😎": "smiling_face_with_sunglasses",
}


def _emoji_key(e: str) -> str:
    return e.replace("\ufe0f", "") if e.replace("\ufe0f", "") in EMOJI_VI else e


def emoji(s: str, mode: str = "keep") -> str:
    """keep | vi (':tên_tiếng_việt:') | en (':english_name:') | remove."""
    if mode in (None, "keep", "none", False):
        return s
    if mode == "remove":
        out = _EMOJI_RE.sub(" ", s)
    elif mode == "vi":
        out = _EMOJI_RE.sub(lambda m: f" :{EMOJI_VI.get(_emoji_key(m.group(0)), 'biểu_tượng')}: ", s)
    elif mode == "en":
        try:  # dùng gói `emoji` nếu có để phủ đủ bảng mã
            import emoji as _emoji_pkg  # type: ignore

            out = _emoji_pkg.demojize(s, delimiters=(" :", ": "))
        except ImportError:
            out = _EMOJI_RE.sub(lambda m: f" :{EMOJI_EN.get(_emoji_key(m.group(0)), 'emoji')}: ", s)
    else:
        raise ValueError(f"emoji mode không hợp lệ: {mode}")
    return _WS_RE.sub(" ", out).strip()


def has_emoji(s: str) -> bool:
    return bool(_EMOJI_RE.search(s or ""))


def strip_emoji(s: str) -> str:
    return _WS_RE.sub(" ", _EMOJI_RE.sub(" ", s or "")).strip()


# --------------------------------------------------------------------------- chữ hoa
_ANGLE_RE = re.compile(r"(<[^<>\s]+>)")


def lowercase(s: str, mode: bool = True) -> str:
    """Chữ thường, nhưng giữ nguyên token đặc biệt dạng <GIÁ>, <SIZE>, <kéo_dài>."""
    if not mode:
        return s
    return "".join(p if _ANGLE_RE.fullmatch(p) else p.lower() for p in _ANGLE_RE.split(s))


# --------------------------------------------------------------------------- placeholder
# Giá: 99k, 99 k, 1tr2, 150 nghìn, 200 ngàn, 1 triệu, 2 củ, 50 cành, 120.000đ, 1,5tr
_PRICE_RE = re.compile(
    r"(?<!\w)\d+(?:[.,]\d+)*\s?(?:k|K|ka|nghìn|nghin|ngàn|ngan|tr\d*|triệu|trieu|củ|cu|cành|canh|đ|d|vnd|vnđ)(?!\w)",
    re.UNICODE,
)
_SIZE_RE = re.compile(r"(?i)(?<!\w)(size|sz|sai|sài|sìze)\s*(xxs|xs|s|m|l|xl|xxl|xxxl|\dxl|\d{2})(?!\w)")
_MENTION_TOKEN_RE = re.compile(r"@[\w.]+")
_NUM_RE = re.compile(r"(?<![\w<])\d+(?:[.,]\d+)*(?![\w>])")


def placeholders(s: str, mode: bool = True) -> str:
    """Thay thực thể bằng token giữ chức năng: @USER, <GIÁ>, <SIZE>, <SỐ>.

    Làm TRƯỚC teencode để '99 k' không bao giờ bị đọc thành '99 không'.
    """
    if not mode:
        return s
    s = _MENTION_TOKEN_RE.sub("@USER", s)
    s = _PRICE_RE.sub("<GIÁ>", s)
    s = _SIZE_RE.sub(lambda m: f"{m.group(1)} <SIZE>", s)
    s = _NUM_RE.sub("<SỐ>", s)
    return s


# --------------------------------------------------------------------------- tách từ
def word_segment(s: str, mode: str = "none", _cache: dict = {}) -> str:  # noqa: B006 (cache có chủ đích)
    """none | rdrsegmenter (VnCoreNLP, khớp PhoBERT) | underthesea (tái lập khóa luận).

    PhoBERT được tiền huấn luyện trên văn bản tách từ bằng RDRSegmenter, nên với PhoBERT hãy dùng
    'rdrsegmenter'. ViSoBERT/XLM-R KHÔNG cần tách từ.
    """
    if mode in (None, "none", False):
        return s
    if mode == "underthesea":
        from underthesea import word_tokenize  # type: ignore

        return word_tokenize(s, format="text")
    if mode == "rdrsegmenter":
        if "rdr" not in _cache:
            import py_vncorenlp  # type: ignore

            from ..config import resolve

            save_dir = str(resolve("data/vncorenlp"))
            import os

            os.makedirs(save_dir, exist_ok=True)
            cwd = os.getcwd()  # py_vncorenlp đổi thư mục làm việc khi khởi tạo -> trả lại sau đó
            try:
                if not os.path.exists(os.path.join(save_dir, "VnCoreNLP-1.2.jar")):
                    py_vncorenlp.download_model(save_dir=save_dir)
                _cache["rdr"] = py_vncorenlp.VnCoreNLP(annotators=["wseg"], save_dir=save_dir)
            finally:
                os.chdir(cwd)
        return " ".join(_cache["rdr"].word_segment(s)) if s.strip() else s
    raise ValueError(f"segment mode không hợp lệ: {mode}")

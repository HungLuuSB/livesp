"""Ghép các bước tiền xử lý theo cấu hình, và sinh danh sách điều kiện cho thí nghiệm ablation.

Thứ tự cố định (có lý do):
    strip_control -> unicode -> tone -> emoji -> elongation -> placeholders -> teencode -> lowercase -> segment
    - emoji trước elongation: để chuỗi emoji lặp không bị gộp nhầm
    - placeholders trước teencode: để '99 k' thành <GIÁ> chứ không thành '99 không'
    - lowercase sau teencode: teencode so khớp không phân biệt hoa thường nên thứ tự này giữ được chữ hoa
      khi lowercase=False
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Callable, Iterable

from . import steps, teencode

FACTORS: dict[str, list] = {
    "unicode": ["none", "nfc"],
    "tone": ["none", "new"],
    "elongation": ["keep", "one", "two", "one_mark"],
    "emoji": ["keep", "vi", "en", "remove"],
    "lowercase": [False, True],
    "teencode": ["none", "naive", "guarded", "contextual"],
    "placeholders": [False, True],
}


@dataclass(frozen=True)
class Condition:
    name: str
    unicode: str = "none"
    tone: str = "none"
    elongation: str = "keep"
    emoji: str = "keep"
    lowercase: bool = False
    teencode: str = "none"
    placeholders: bool = False
    segment: str = "none"  # chỉ đặt theo mô hình (PhoBERT -> rdrsegmenter), không phải yếu tố ablation

    def levels(self) -> dict:
        d = asdict(self)
        d.pop("name")
        return d


RAW = Condition("RAW")
FULL = Condition(
    "FULL", unicode="nfc", tone="new", elongation="one_mark", emoji="vi",
    lowercase=True, teencode="guarded", placeholders=True,
)
# Tái lập gần đúng khóa luận: NFC, emoji->tiếng Anh, rút ký tự lặp, từ điển thuần, chữ thường, tách từ underthesea.
THESIS = Condition(
    "THESIS", unicode="nfc", tone="none", elongation="one", emoji="en",
    lowercase=True, teencode="naive", placeholders=False, segment="underthesea",
)


def build(cond: Condition) -> Callable[[str], str]:
    def run(s: str) -> str:
        s = steps.strip_control(s)
        s = steps.unicode_nfc(s, cond.unicode)
        s = steps.tone_placement(s, cond.tone)
        s = steps.emoji(s, cond.emoji)
        s = steps.elongation(s, cond.elongation)
        s = steps.placeholders(s, cond.placeholders)
        s = teencode.normalize(s, cond.teencode)
        s = steps.lowercase(s, cond.lowercase)
        s = steps.word_segment(s, cond.segment)
        return steps.strip_control(s)

    return run


def apply(cond: Condition, texts: Iterable[str]) -> list[str]:
    texts = list(texts)
    if cond.teencode == "contextual":
        # Bộ chuẩn hóa ngữ cảnh chạy theo lô cho nhanh: tách bước teencode ra khỏi hàm từng câu.
        pre = build(replace(cond, teencode="none", lowercase=False, segment="none"))
        mid = teencode.contextual_normalize([pre(t) for t in texts])
        post = build(Condition("post", lowercase=cond.lowercase, segment=cond.segment))
        return [post(t) for t in mid]
    f = build(cond)
    return [f(t) for t in texts]


def generate_conditions(include_contextual: bool = False) -> list[Condition]:
    """RAW, FULL, THESIS + thêm từng bước từ RAW (forward) + bỏ từng bước khỏi FULL (leave-one-out)."""
    conds: list[Condition] = [RAW, FULL, THESIS]
    raw_levels = RAW.levels()
    full_levels = FULL.levels()
    for factor, levels in FACTORS.items():
        for lv in levels:
            if lv == raw_levels[factor]:
                continue
            if lv == "contextual" and not include_contextual:
                continue
            conds.append(replace(RAW, name=f"RAW+{factor}={lv}", **{factor: lv}))
    for factor in FACTORS:
        if full_levels[factor] == raw_levels[factor]:
            continue
        conds.append(replace(FULL, name=f"FULL-{factor}", **{factor: raw_levels[factor]}))
    if include_contextual:
        conds.append(replace(FULL, name="FULL+teencode=contextual", teencode="contextual"))
    # Bỏ trùng theo cấu hình mức (giữ tên xuất hiện đầu tiên).
    seen, uniq = set(), []
    for c in conds:
        key = tuple(sorted(c.levels().items()))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def for_model(cond: Condition, model_family: str) -> Condition:
    """PhoBERT được tiền huấn luyện trên văn bản đã tách từ -> luôn tách từ bằng RDRSegmenter.

    Riêng điều kiện THESIS giữ underthesea để tái lập đúng khóa luận.
    """
    if model_family.lower().startswith("phobert") and cond.segment == "none":
        return replace(cond, segment="rdrsegmenter")
    return cond


def by_name(name: str, include_contextual: bool = False) -> Condition:
    for c in generate_conditions(include_contextual):
        if c.name == name:
            return c
    raise KeyError(name)

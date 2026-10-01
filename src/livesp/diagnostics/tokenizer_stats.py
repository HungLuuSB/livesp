"""Chẩn đoán miền phía tokenizer: tokenizer có "nhìn thấy" chat livestream như một chuỗi từ, hay cắt vụn?

Đo, cho mỗi (mô hình × điều kiện tiền xử lý):
    pieces_per_word   số subword trung bình trên mỗi từ (cách nhau bởi khoảng trắng)
    share_split_ge3   tỷ lệ từ bị cắt thành >= 3 mảnh
    unk_rate          tỷ lệ token UNK
Và hai phép kiểm tra đồng nhất: NFC == NFD? dấu thanh cũ == mới? (nếu True, yếu tố đó vô nghĩa với mô hình đó)

Chạy: python -m livesp.diagnostics.tokenizer_stats --texts data/annotations/sample_items --n 2000
"""
from __future__ import annotations

import argparse
import unicodedata

import pandas as pd

from ..config import resolve
from ..data.ingest import load
from ..preprocess import pipeline

TONE_PAIRS = [("hòa", "hoà"), ("thủy", "thuỷ"), ("khỏe", "khoẻ"), ("hóa", "hoá"), ("tùy", "tuỳ")]


def fertility(tok, texts: list[str]) -> dict:
    words = [w for t in texts for w in t.split()]
    pieces = [len(tok.tokenize(w)) for w in words]
    all_tokens = [p for t in texts for p in tok.tokenize(t)]
    unk = tok.unk_token
    return {
        "n_words": len(words),
        "pieces_per_word": sum(pieces) / max(len(words), 1),
        "share_split_ge3": sum(p >= 3 for p in pieces) / max(len(words), 1),
        "unk_rate": sum(t == unk for t in all_tokens) / max(len(all_tokens), 1),
    }


def identity_checks(tok, texts: list[str]) -> dict:
    same_nfc = sum(tok(unicodedata.normalize("NFC", t))["input_ids"] == tok(unicodedata.normalize("NFD", t))["input_ids"]
                   for t in texts)
    same_tone = sum(tok(a)["input_ids"] == tok(b)["input_ids"] for a, b in TONE_PAIRS)
    return {"nfc_equals_nfd_share": same_nfc / max(len(texts), 1), "tone_old_equals_new_share": same_tone / len(TONE_PAIRS)}


def main() -> None:
    from transformers import AutoTokenizer

    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", default="data/annotations/sample_items")
    ap.add_argument("--models", default="uitnlp/visobert,vinai/phobert-base-v2,xlm-roberta-base")
    ap.add_argument("--conditions", default="RAW,FULL,THESIS,RAW+teencode=naive,RAW+elongation=one,RAW+emoji=en")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--out", default="results/diagnostics/tokenizer_stats.csv")
    a = ap.parse_args()
    df = load(a.texts)
    texts = df["text_raw"].dropna().astype(str).sample(min(a.n, len(df)), random_state=0).tolist()
    rows = []
    for m in a.models.split(","):
        tok = AutoTokenizer.from_pretrained(m)
        rows.append({"model": m, "condition": "(identity)", **identity_checks(tok, texts[:500])})
        for cname in a.conditions.split(","):
            cond = pipeline.for_model(pipeline.by_name(cname), m.split("/")[-1])
            rows.append({"model": m, "condition": cname, **fertility(tok, pipeline.apply(cond, texts))})
            print(rows[-1])
    out = resolve(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"-> {out}")


if __name__ == "__main__":
    main()

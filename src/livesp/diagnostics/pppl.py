"""Pseudo-perplexity (Salazar và cộng sự, 2020) để đo khoảng cách miền của một mô hình MLM.

PPPL = exp(- Σ log P(token_i | câu với token_i bị che) / Σ số token). So sánh CÙNG một mô hình trên:
    (a) chat livestream của bạn  và  (b) bình luận mạng xã hội thông thường (một tập công khai).
PPPL(a) >> PPPL(b) là bằng chứng định lượng rằng miền livestream lệch khỏi dữ liệu tiền huấn luyện.
Không so PPPL giữa các mô hình khác tokenizer.

Chạy: python -m livesp.diagnostics.pppl --model uitnlp/visobert --texts data/annotations/sample_items \
          --reference data/reference/social_comments.txt --n 2000
"""
from __future__ import annotations

import argparse
import math

import numpy as np

from ..config import resolve
from ..data.ingest import load


def pseudo_perplexity(model_name: str, texts: list[str], max_len: int = 64, batch: int = 128) -> dict:
    import torch
    from transformers import AutoModelForMaskedLM, AutoTokenizer

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForMaskedLM.from_pretrained(model_name).to(dev).eval()
    total_lp, total_n = 0.0, 0
    per_text = []
    for t in texts:
        ids = tok(t, truncation=True, max_length=max_len, return_tensors="pt")["input_ids"][0]
        special = set(tok.all_special_ids)
        pos = [i for i, x in enumerate(ids.tolist()) if x not in special]
        if not pos:
            continue
        lp = 0.0
        for s in range(0, len(pos), batch):
            chunk = pos[s : s + batch]
            x = ids.repeat(len(chunk), 1)
            for r, p in enumerate(chunk):
                x[r, p] = tok.mask_token_id
            with torch.no_grad():
                logits = model(input_ids=x.to(dev)).logits
            logp = torch.log_softmax(logits, -1)
            for r, p in enumerate(chunk):
                lp += float(logp[r, p, ids[p]])
        total_lp += lp
        total_n += len(pos)
        per_text.append(math.exp(-lp / len(pos)))
    return {"pppl": math.exp(-total_lp / max(total_n, 1)), "median_text_pppl": float(np.median(per_text)),
            "n_texts": len(per_text), "n_tokens": total_n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="uitnlp/visobert")
    ap.add_argument("--texts", default="data/annotations/sample_items")
    ap.add_argument("--reference", default=None, help="file .txt, mỗi dòng một bình luận mạng xã hội thông thường")
    ap.add_argument("--n", type=int, default=2000)
    a = ap.parse_args()
    df = load(a.texts)
    live = df["text_raw"].dropna().astype(str).sample(min(a.n, len(df)), random_state=0).tolist()
    print("livestream:", pseudo_perplexity(a.model, live))
    if a.reference:
        ref = [l for l in resolve(a.reference).read_text(encoding="utf-8").splitlines() if l.strip()]
        rng = np.random.default_rng(0)
        ref = list(rng.choice(ref, min(a.n, len(ref)), replace=False))
        print("tham chiếu:", pseudo_perplexity(a.model, ref))


if __name__ == "__main__":
    main()

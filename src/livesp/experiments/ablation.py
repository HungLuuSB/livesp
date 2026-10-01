"""Thí nghiệm tiền xử lý (Study 1, RQ2): điều kiện × mô hình × seed × cỡ tập huấn luyện.

CHẠY TIẾP ĐƯỢC: mỗi lượt lưu dự đoán ra file .npy; lượt nào đã có file thì bỏ qua. Dừng máy giữa chừng,
chạy lại đúng lệnh là tiếp tục.

    python -m livesp.experiments.ablation run --task sentiment --models tfidf --conditions all --seeds 5
    python -m livesp.experiments.ablation run --task sp --models visobert,phobert,xlmr --conditions all --seeds 5
    python -m livesp.experiments.ablation run --task sp --models visobert --conditions RAW,FULL --train-sizes 500,1000,2000,4000
    python -m livesp.experiments.ablation summarize --task sp

Nhãn vàng: data/annotations/gold (item_id, session_id, split, text_raw, HOST..TRANS, sentiment).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_yaml, resolve
from ..data.ingest import load
from ..eval.metrics import macro_f1, per_label_f1
from ..eval.significance import approx_randomization, holm, paired_bootstrap
from ..eval.slices import slice_report
from ..labels import SENTIMENT_LABELS, SP_LABELS
from ..models.baselines import RuleClassifier, TfidfLR
from ..preprocess import pipeline


def _task_setup(gold: pd.DataFrame, task: str):
    if "needs_adjudication" in gold.columns:  # bỏ mục chưa phân xử xong
        gold = gold[~gold["needs_adjudication"].astype(str).str.lower().isin(["true", "1"])]
    gold = gold.copy()
    if task == "sentiment":
        gold = gold[gold["sentiment"].isin(SENTIMENT_LABELS)]
        y = gold["sentiment"].map(SENTIMENT_LABELS.index).to_numpy()
        return gold, y, SENTIMENT_LABELS, "multiclass"
    y = gold[SP_LABELS].astype(float).fillna(0).astype(int).to_numpy()
    return gold, y, SP_LABELS, "multilabel"


def _subsample(idx: np.ndarray, size, seed: int) -> np.ndarray:
    if size in (None, "full") or int(size) >= len(idx):
        return idx
    return np.random.default_rng(seed).choice(idx, int(size), replace=False)


def run(task: str, models: list[str], conditions: list[str], seeds: int, train_sizes: list,
        gold_path: str, cfg: dict, out_root: str, include_contextual: bool = False) -> None:
    gold, y, labels, mtype = _task_setup(load(gold_path), task)
    texts_raw = gold["text_raw"].fillna("").astype(str).tolist()
    split = gold["split"].to_numpy()
    tr, dv, te = (np.where(split == s)[0] for s in ("train", "dev", "test"))
    all_conds = pipeline.generate_conditions(include_contextual)
    conds = all_conds if conditions == ["all"] else [pipeline.by_name(c, include_contextual) for c in conditions]
    out = resolve(out_root) / task
    (out / "preds").mkdir(parents=True, exist_ok=True)
    np.save(out / "y_test.npy", y[te])
    pd.Series(np.asarray(texts_raw)[te]).to_csv(out / "test_texts.csv", index=False)
    runs_csv = out / "runs.csv"
    cache: dict = {}
    for mname in models:
        mcfg = cfg["models"][mname]
        family = mcfg.get("family", mname)
        for cond0 in conds:
            if mcfg["type"] == "rules" and cond0.name != "RAW":
                continue
            cond = pipeline.for_model(cond0, family)
            key = (cond.name, cond.segment)
            if key not in cache:
                cache[key] = np.asarray(pipeline.apply(cond, texts_raw), dtype=object)
            X = cache[key]
            for size in train_sizes:
                for seed in range(seeds):
                    tag = f"{cond0.name}__{mname}__s{seed}__n{size}"
                    fpred = out / "preds" / f"{tag}.npy"
                    if fpred.exists():
                        continue
                    tr_s = _subsample(tr, size, seed)
                    t0 = time.time()
                    extra = {"throughput_per_s": np.nan, "dev_best": np.nan, "gpu": ""}  # cột cố định cho runs.csv
                    if mcfg["type"] == "rules":
                        pred = RuleClassifier(labels).predict(X[te])
                    elif mcfg["type"] == "tfidf":
                        m = TfidfLR(mtype, seed=seed).fit(X[tr_s], y[tr_s])
                        t1 = time.time()
                        pred = m.predict(X[te])
                        extra["throughput_per_s"] = len(te) / max(time.time() - t1, 1e-6)
                    elif mcfg["type"] == "hf":
                        from ..models.hf_finetune import train_eval

                        r = train_eval(mcfg["hf_id"], (X[tr_s], y[tr_s]), (X[dv], y[dv]), (X[te], y[te]), mtype,
                                       len(labels), seed=seed, max_len=cfg.get("max_len", 64),
                                       epochs=mcfg.get("epochs", 5), lr=mcfg.get("lr", 3e-5),
                                       batch=mcfg.get("batch", 32), trust_remote_code=mcfg.get("trust_remote_code", False),
                                       out_dir=str(out / "_ckpt"))
                        pred = r["pred"]
                        extra.update({k: r[k] for k in ("throughput_per_s", "dev_best", "gpu")})
                    else:
                        raise ValueError(mcfg["type"])
                    np.save(fpred, pred)
                    row = {"condition": cond0.name, "model": mname, "seed": seed, "train_size": size,
                           "n_train": len(tr_s), "macro_f1": macro_f1(y[te], pred),
                           "per_label": json.dumps(per_label_f1(y[te], pred, labels)),
                           "seconds": round(time.time() - t0, 1), **extra}
                    pd.DataFrame([row]).to_csv(runs_csv, mode="a", header=not runs_csv.exists(), index=False)
                    print(f"{tag}: macro-F1 = {row['macro_f1']:.4f}")


def _vote(preds: list[np.ndarray]) -> np.ndarray:
    arr = np.stack(preds)
    if arr.ndim == 3:  # đa nhãn: đa số theo từng nhãn
        return (arr.mean(0) >= 0.5).astype(int)
    return np.apply_along_axis(lambda c: np.bincount(c).argmax(), 0, arr)


def summarize(task: str, out_root: str, train_size="full", n_boot: int = 1000, n_perm: int = 2000) -> None:
    out = resolve(out_root) / task
    runs = pd.read_csv(out / "runs.csv")
    y = np.load(out / "y_test.npy")
    texts = pd.read_csv(out / "test_texts.csv").iloc[:, 0].fillna("").astype(str).tolist()
    summ = runs.groupby(["model", "condition", "train_size"])["macro_f1"].agg(["mean", "std", "count"]).reset_index()
    summ.to_csv(out / "summary.csv", index=False)
    voted = {}
    for (m, c), g in runs[runs["train_size"].astype(str) == str(train_size)].groupby(["model", "condition"]):
        preds = [np.load(out / "preds" / f"{c}__{m}__s{s}__n{train_size}.npy", allow_pickle=True) for s in g["seed"]]
        voted[(m, c)] = _vote(preds)
    comps = []
    for m in sorted({k[0] for k in voted}):
        conds = {c for (mm, c) in voted if mm == m}
        pairs = [(c, "RAW") for c in conds if c.startswith("RAW+") or c in ("FULL", "THESIS")]
        pairs += [("FULL", c) for c in conds if c.startswith("FULL-")]
        rows = []
        for a, b in pairs:
            if (m, a) in voted and (m, b) in voted:
                pb = paired_bootstrap(y, voted[(m, a)], voted[(m, b)], n_boot=n_boot)
                ar = approx_randomization(y, voted[(m, a)], voted[(m, b)], n_perm=n_perm)
                rows.append({"model": m, "A": a, "B": b, **pb, **ar})
        if rows:
            df = pd.DataFrame(rows)
            df["p_holm"] = holm(df["p_ar"])
            comps.append(df)
    if comps:
        pd.concat(comps).to_csv(out / "comparisons.csv", index=False)
    sl = [slice_report(texts, y, p).assign(model=m, condition=c) for (m, c), p in voted.items()]
    if sl:
        pd.concat(sl).to_csv(out / "slices.csv", index=False)
    print(summ.sort_values("mean", ascending=False).head(20).to_string(index=False))
    print(f"-> {out}/summary.csv, comparisons.csv, slices.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--task", choices=["sentiment", "sp"], required=True)
    r.add_argument("--models", default="tfidf")
    r.add_argument("--conditions", default="all")
    r.add_argument("--seeds", type=int, default=5)
    r.add_argument("--train-sizes", default="full")
    r.add_argument("--gold", default="data/annotations/gold")
    r.add_argument("--config", default="configs/experiment.yaml")
    r.add_argument("--out", default="results/ablation")
    r.add_argument("--contextual", action="store_true")
    s = sub.add_parser("summarize")
    s.add_argument("--task", choices=["sentiment", "sp"], required=True)
    s.add_argument("--out", default="results/ablation")
    s.add_argument("--train-size", default="full")
    a = ap.parse_args()
    if a.cmd == "run":
        cfg = load_yaml(a.config)
        sizes = [x if x == "full" else int(x) for x in a.train_sizes.split(",")]
        run(a.task, a.models.split(","), a.conditions.split(","), a.seeds, sizes, a.gold, cfg, a.out, a.contextual)
    else:
        summarize(a.task, a.out, a.train_size)


if __name__ == "__main__":
    main()

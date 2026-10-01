# livesp — Sự hiện diện xã hội được biểu đạt trong chat livestream thương mại tiếng Việt

Mã nguồn cho đề xuất nâng cấp khóa luận thành hai bài báo (xem `docs/PROPOSAL_SUMMARY.md`).

## Bắt đầu nhanh (WSL 2 Ubuntu)
```bash
cd ~/projects/livesp && bash scripts/setup_wsl.sh
source .venv/bin/activate && make test && make smoke
```
Hướng dẫn đầy đủ WSL 2 + VS Code + Claude Code: `docs/SETUP_WSL2_VSCODE_CLAUDECODE.md`.
Việc cần làm theo thứ tự: `docs/CLAUDE_CODE_TASKS.md`.

## Luồng dữ liệu
```
capture (TikTokLive, ẩn danh lúc ghi) -> data/raw/*.jsonl
ingest   -> data/interim/events, sessions        (dựng phiên, chất lượng phiên)
filters  -> data/processed/comments              (6 bộ lọc có mẫu kiểm tay)
sampling -> data/annotations/to_label_*.csv      (chia tập theo phiên)
merge    -> gold + reliability (Krippendorff α)
ablation -> results/ablation/<task>/             (22 điều kiện × mô hình × seed; chạy tiếp được)
predict  -> comments_pred -> panel.analyze -> results/panel/
```

## Trạng thái
| Thành phần | Trạng thái |
| --- | --- |
| Tiền xử lý, teencode, 22 điều kiện | Đã test |
| Ẩn danh (hash, che SĐT/email) | Đã test |
| Ingest, dựng phiên, sàng lọc | Đã test trên dữ liệu giả lập |
| Krippendorff α | Đã test (khớp ví dụ chuẩn 0,743) |
| Kiểm định cặp, Holm, lát cắt | Đã test |
| Bộ chạy ablation (luật, TF-IDF) | Đã test end-to-end |
| FE + SE cụm | Đã test (khớp LSDV) |
| Fine-tune HF, DAPT, PPPL, tokenizer stats, LLM | Viết theo API chuẩn, CHƯA chạy (cần GPU/mạng) — chạy thử ở Task 7–12 |
| Recorder/scheduler TikTokLive | Adapter CHƯA kiểm chứng — Task 1 |

## Quyền riêng tư
Username và @mention được băm (HMAC, salt trong `.env`) ngay lúc ghi; SĐT/email bị che. Không commit `data/`.

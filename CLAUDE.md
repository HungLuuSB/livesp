# CLAUDE.md — bộ nhớ dự án cho Claude Code

Trả lời tôi bằng **tiếng Việt**. Tôi là Lưu Thái Hưng; đây là dự án nâng cấp khóa luận thành hai bài báo Q2/Q3.

## Dự án là gì
Đo **sự hiện diện xã hội được biểu đạt (expressed social presence)** trong chat livestream TikTok Shop tiếng Việt,
KHÔNG dùng khảo sát Likert. Hai nghiên cứu:
- **Study 1 (dữ liệu 10/2026):** codebook 6 nhãn (HOST, VIEWER, COLLECTIVE, AFFECT, SELF, TRANS), ~6.000 bình luận
  gán nhãn, thí nghiệm tiền xử lý 22 điều kiện × nhiều mô hình × 5 seed, DAPT, baseline LLM.
- **Study 2 (dữ liệu 11–12/2026):** bảng theo phút, hồi quy hiệu ứng cố định có trễ: SP ở t có đi trước kết cục ở t+1?
Đề xuất đầy đủ: docs/PROPOSAL_SUMMARY.md (bản gốc là Claude Doc, link trong file đó). Codebook: docs/CODEBOOK.md.
Danh sách việc: docs/CLAUDE_CODE_TASKS.md (dùng lệnh `/next-task`).

## Lệnh
- `make test` — unit test, không cần GPU/mạng. Chạy trước khi báo xong BẤT KỲ việc gì.
- `make smoke` — toàn pipeline trên dữ liệu giả lập (data/synth).
- `make capture-one CHANNEL=x` — thử ghi 1 kênh 5 phút. `make capture` — bộ lập lịch.
- `make ingest filter sample merge` — xử lý dữ liệu thật theo thứ tự.
- `make ablation-cpu`, `make ablation-gpu`, `make summarize`, `make dapt`, `make panel-dev`.
- Môi trường Python: `.venv/` (kích hoạt: `source .venv/bin/activate`). `PYTHONPATH=src` đã đặt trong Makefile.

## Cấu trúc
`src/livesp/{capture,data,preprocess,annotate,models,diagnostics,eval,experiments,panel}` — xem docstring đầu mỗi file.
`configs/` cấu hình YAML; `configs/FROZEN` liệt kê cấu hình đã đóng băng. `tests/` unittest (chạy được bằng pytest).

## Quy tắc code
- `preprocess/steps.py`: mọi bước là hàm thuần `str -> str` có tham số `mode`. Không đổi THỨ TỰ trong
  `pipeline.build` nếu chưa hỏi tôi (thứ tự có lý do, ghi ở docstring).
- Mọi hàm mới phải có test. Ưu tiên numpy/pandas/sklearn; import torch/transformers BÊN TRONG hàm.
- GPU 6 GB (GTX 1660 Super): max_len 64, batch 32, fp16; nếu OOM thì batch 16 + gradient accumulation.
- Code TikTokLive trong `capture/recorder.py` là adapter CHƯA kiểm chứng với bản đã cài — Task 1.

## Toàn vẹn nghiên cứu (bắt buộc)
- KHÔNG phân tích kết cục trên dữ liệu kiểm định (từ 01/11/2026) khi `configs/FROZEN` chưa có filters.yaml và panel.yaml.
- KHÔNG sửa file có tên trong `configs/FROZEN`. Cần thay đổi -> dừng lại, hỏi tôi, ghi vào docs/DEVIATIONS.md.
- Chia train/dev/test THEO PHIÊN. Kho DAPT phải loại phiên test. Người gán nhãn chỉ thấy VĂN BẢN THÔ.
- Siêu tham số giữ cố định giữa các điều kiện tiền xử lý; chỉ đầu vào thay đổi.
- Không ghi đè kết quả đã chạy: điều kiện mới = tên mới. Không xóa dòng trong results/**/runs.csv.
- Không "sửa" dữ liệu để kết quả đẹp hơn. Kết quả null vẫn báo cáo.

## Quyền riêng tư (bắt buộc)
- Không đọc `.env`. Không in, không ghi username/nickname thật; chỉ dùng hash (HMAC + salt).
- Bình luận đi qua `privacy.clean_comment_text` (che SĐT/email, băm @mention) TRƯỚC khi ghi đĩa.
- Không commit gì trong `data/`, `results/`, `models/`. Tên kênh thật không xuất hiện trong bài báo.

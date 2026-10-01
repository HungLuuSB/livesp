# Danh sách việc cho Claude Code

Cách dùng: trong VS Code, mở khung Claude Code và gõ `/next-task`, hoặc dán "Prompt gợi ý" của từng task.
Mỗi task: Claude đề xuất kế hoạch → bạn duyệt → Claude làm → `make test` → bạn review diff → commit.
Thứ tự đã sắp theo lịch: Task 1–4 phải xong TRƯỚC 10.10.

## Giai đoạn A — Thu thập (trước 10/10/2026)

- [x] **Task 0 — Làm quen.** Prompt: "Đọc CLAUDE.md, docs/PROPOSAL_SUMMARY.md và lướt src/. Tóm tắt kiến trúc repo trong
  10 dòng và liệt kê 5 rủi ro kỹ thuật lớn nhất. Chưa sửa gì." Xong khi: bạn thấy bản tóm tắt đúng.
- [x] **Task 1 — Kiểm chứng adapter TikTokLive.** Chép `capture.py` cũ của khóa luận vào `legacy/capture_thesis.py`.
  Prompt: "Kiểm tra phiên bản TikTokLive đã cài (pip show TikTokLive). Đọc mã nguồn thư viện trong .venv để xác nhận:
  tên lớp sự kiện, thuộc tính user/unique_id, trường số người xem của RoomUserSeqEvent, cách gọi is_live/connect.
  Sửa src/livesp/capture/recorder.py cho khớp, tham khảo legacy/capture_thesis.py. Viết test cho handle() bằng đối tượng
  giả." Sau đó: `make capture-one CHANNEL=<kênh đang live>`. Xong khi: file JSONL có comment/like/viewer, user đã băm,
  text đã che SĐT, có dòng _meta connect/disconnect.
- [ ] **Task 2 — Chạy thử bộ lập lịch.** Tạo configs/channels.csv với 3 kênh. Chạy `make capture` trong tmux 2 giờ.
  Prompt: "Viết scripts/capture_status.py: đọc data/raw/_heartbeat.json và các file JSONL hôm nay, in bảng kênh | phiên |
  số sự kiện | phút mất kết nối | nhịp tim cuối. Cảnh báo nếu nhịp tim cũ hơn 5 phút." Sau đó cài systemd service
  (scripts/wsl/livesp-capture.service). Xong khi: tắt/mở mạng thử mà recorder tự nối lại.
- [ ] **Task 3 — Danh sách kênh theo khung 20 ô.** Prompt: "Viết scripts/validate_channels.py kiểm tra configs/channels.csv:
  đủ 5 nhóm ngành × 4 tầng follower, mỗi ô 8–10 kênh, không trùng kênh, không có '@'. In bảng ô còn thiếu." Bạn tự
  tìm kênh; Claude chỉ kiểm tra. Xong khi: 160–200 kênh, đủ các ô.
- [ ] **Task 4 — Sàng lọc trên dữ liệu thật.** Sau 1–2 ngày thu: `make ingest filter`. Prompt: "Đọc data/audit/filter_audit,
  liệt kê các mẫu 'đã mua' lọt lưới hoặc bị bắt nhầm; đề xuất sửa configs/filters.yaml (chưa đóng băng). Viết
  scripts/audit_metrics.py tính precision/recall từ cột audit_correct sau khi tôi điền." Xong khi: mỗi bộ lọc precision ≥ 0,9.

## Giai đoạn B — Study 1 (10/2026 – 02/2027)

- [ ] **Task 5 — Dữ liệu khóa luận làm pilot.** Prompt: "Viết scripts/import_thesis_data.py chuyển dữ liệu 30 phiên cũ về
  lược đồ events (type, channel, ts, user băm lại bằng salt mới, text qua clean_comment_text), để trống session_hint
  (ingest sẽ tách theo khoảng lặng)." Dùng để tập huấn người gán nhãn, KHÔNG dùng để kiểm định.
- [ ] **Task 6 — Gán nhãn.** `make sample` → gửi to_label_A/B/C.csv. Tùy chọn prompt: "Tạo cấu hình Label Studio
  (labeling config XML) cho 6 nhãn đa chọn + sentiment + hiển thị context_before." Gán xong: đổi tên thành labeled_X.csv,
  `make merge`. Xong khi: reliability.csv có α ≥ 0,667 cho mọi nhãn giữ lại.
- [ ] **Task 7 — Chẩn đoán miền.** Tìm một tập bình luận mạng xã hội tiếng Việt công khai làm tham chiếu (kiểm tra giấy phép),
  lưu data/reference/social_comments.txt. `make diag` rồi `python -m livesp.diagnostics.pppl --reference ...`.
  Prompt: "Tổng hợp results/diagnostics thành một bảng và 2 biểu đồ cho Bài A."
- [ ] **Task 8 — Ablation CPU.** `make ablation-cpu && make summarize`. Prompt: "Đọc results/ablation/*/comparisons.csv và
  slices.csv; viết notebooks/ablation_report.ipynb vẽ forest plot Δ macro-F1 (có CI) theo điều kiện, và heatmap F1 theo lát
  cắt × điều kiện."
- [ ] **Task 9 — Chuẩn hóa theo ngữ cảnh + chuẩn vàng chuẩn hóa.** Chuẩn hóa tay 500 bình luận → data/annotations/norm_gold.csv
  (text_raw, text_norm). Prompt: "Viết src/livesp/eval/normalizer_eval.py: với mỗi mức teencode (naive, guarded,
  contextual), tính tỷ lệ token sửa đúng, bỏ sót, và 'chuẩn hóa quá tay' so với norm_gold. Đăng ký một backend
  contextual qua teencode.register_contextual_backend (LLM trong models/llm_baseline.py hoặc mô hình seq2seq)."
- [ ] **Task 10 — Ablation GPU.** `make ablation-gpu` trong tmux (chạy tiếp được nếu ngắt). Nếu OOM: batch 16 trong
  configs/experiment.yaml cho MỌI điều kiện của mô hình đó (giữ cố định giữa điều kiện).
- [ ] **Task 11 — DAPT.** `make dapt`, rồi thêm visobert_dapt vào ablation. Nếu GPU không đủ: chạy trên Kaggle/Colab
  (Prompt: "Tạo notebook chạy livesp.models.dapt trên Kaggle, đọc corpus từ dataset upload").
- [ ] **Task 12 — Baseline LLM.** Prompt: "Viết scripts/run_llm_baseline.py: chạy models/llm_baseline.label trên TẬP TEST,
  lưu dự đoán theo đúng định dạng results/ablation/<task>/preds để summarize so sánh được. Báo chi phí ước tính trước khi chạy."
- [ ] **Task 13 — Kiểm chứng RESP.** Prompt: "Viết công cụ nghe tay đơn giản (HTML cục bộ): phát audio mẫu, hiện danh sách
  câu hỏi hướng host kèm mốc thời gian, cho tôi đánh dấu host có trả lời không. Sau đó tính precision/recall của
  answered_proxy." Xong khi: precision ≥ 0,70 (nếu không: tắt use_resp trong configs/panel.yaml).
- [ ] **Task 14 — Bảng và hình cho Bài A.**

## Giai đoạn C — Study 2 (11/2026 – 06/2027)

- [ ] **Task 15 — Đóng băng + OSF (TRƯỚC 01/11/2026).** Hoàn thiện docs/PREREG_OSF_DRAFT.md, nộp OSF, tạo configs/FROZEN
  với `filters.yaml` và `panel.yaml`. Từ đây Claude Code không được sửa hai file đó.
- [ ] **Task 16 — Gán nhãn toàn bộ + dựng bảng.** Huấn luyện mô hình tốt nhất (save_to), `python -m livesp.models.predict ...`,
  rồi `python -m livesp.panel.analyze`.
- [ ] **Task 17 — Đa vũ trụ.** Prompt: "Viết scripts/run_multiverse.py dùng panel/fe.py::multiverse với các lựa chọn trong
  configs/panel.yaml; vẽ specification curve (hệ số + CI, bên dưới là ma trận lựa chọn)."
- [ ] **Task 18 — Bảng và hình cho Bài B.**

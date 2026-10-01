"""livesp — đo sự hiện diện xã hội (SP) được biểu đạt trong chat livestream thương mại tiếng Việt.

Các gói con:
    capture      thu thập sự kiện livestream (TikTokLive), ẩn danh ngay lúc ghi
    data         đọc dữ liệu thô, dựng phiên, sàng lọc có kiểm chứng
    preprocess   các bước chuẩn hóa văn bản dạng hàm thuần, ghép theo cấu hình
    annotate     lấy mẫu gán nhãn, chia tập theo phiên, Krippendorff's alpha
    models       baseline luật/TF-IDF, fine-tune transformer, DAPT, LLM
    diagnostics  độ phân mảnh tokenizer, pseudo-perplexity
    eval         chỉ số, kiểm định ý nghĩa cặp, đánh giá theo lát cắt
    experiments  bộ chạy thí nghiệm tiền xử lý (ablation), có thể chạy tiếp khi dừng giữa chừng
    panel        dữ liệu bảng theo phút, proxy phản hồi RESP, hồi quy hiệu ứng cố định
"""

__version__ = "0.1.0"

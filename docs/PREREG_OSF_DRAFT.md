# Bản nháp đăng ký trước (OSF) — Study 2

Hoàn thiện và nộp trước 01/11/2026. Mọi sai lệch sau khi nộp ghi vào docs/DEVIATIONS.md.

## 1. Giả thuyết
- H4a: Tỷ lệ VIEWER + COLLECTIVE ở phút t dự báo dương asinh(like) và asinh(share) ở phút t+1.
- H4b: Tỷ lệ HOST và RESP ở phút t dự báo dương Δlog(người xem) từ t đến t+1.
- H4c: Hệ số của H4a–H4b giữ dấu và ý nghĩa khi ước lượng song song mô hình chiều ngược.

## 2. Thiết kế
Quan sát, dữ liệu bảng theo phút, không can thiệp. Dữ liệu thu 01/11–31/12/2026 bằng pipeline trong kho mã (commit: ____).

## 3. Kế hoạch lấy mẫu
160–200 kênh theo 5 nhóm ngành × 4 tầng follower, mỗi ô 8–10 kênh.
Nhóm ngành: thời trang, mỹ phẩm, mẹ & bé, gia dụng, thực phẩm.
[CẦN CHỐT trước khi nộp: đang thu thêm ngành công nghệ và có thể mở rộng thêm ngành — nếu giữ, cập nhật
số ngành, số ô và tổng số kênh ở trên.] Tầng follower (số TikTok hiển thị lúc chọn kênh, cố
định sau đó): < 100 nghìn; 100–500 nghìn; 500 nghìn – 1 triệu; ≥ 1 triệu. Tối thiểu 300 phiên hợp lệ; dừng thu 31/12/2026 hoặc khi đạt 600 phiên.
Tiêu chí phiên hợp lệ: ghi từ lúc lên sóng; ≥ 30 phút; mất kết nối ≤ 10%; ≥ 150 bình luận người xem sau lọc.

## 4. Biến
- Độc lập: share_HOST, share_VIEWER, share_collective, share_AFFECT, share_SELF, resp_share (nếu H3c đạt).
  Bộ phân loại: mô hình tốt nhất từ Study 1 (tên + commit: ____), huấn luyện trên dữ liệu 10/2026.
- Kết cục: y_dlog_viewers, y_like, y_share, y_join, y_follow, y_gift (t+1).
- Kiểm soát: share_TRANS, share_sent_pos, log_comments, has_comments, biến trễ của kết cục, nhóm phút trong phiên.

## 5. Phân tích
Hồi quy within (hiệu ứng cố định phiên), hiệu ứng nhóm phút, SE cụm theo kênh, trễ K = 3 (chính), K = 1 và 5 (độ vững).
Suy luận: α = 0,05 hai phía; hiệu chỉnh Holm trong mỗi họ giả thuyết (H4a: 2 kết cục; H4b: 2 biến).
Chiều ngược: mô hình đối xứng SP(t+1) ~ kết cục(t).

## 6. Loại trừ dữ liệu
Theo configs/filters.yaml (đã đóng băng, hash SHA-256: ____). Nhóm nghi seeding: phân tích chính GIỮ, độ vững BỎ.

## 7. Đa vũ trụ (độ vững, không thay kết luận chính)
Cửa sổ 1/2/5 phút × trễ 1/3/5 × seeding giữ/bỏ × bộ phân loại tốt nhất/thứ hai × tiền xử lý tốt nhất/THESIS × ngày sale có/không.

## 8. Khám phá (không kiểm định)
RQ5: khác biệt theo ngành hàng, tầng follower, ngày sale lớn (mô hình hỗn hợp, hiệu ứng ngẫu nhiên theo kênh).

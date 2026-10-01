# Codebook v0.1 — Chỉ báo sự hiện diện xã hội trong chat livestream bán hàng

**Đơn vị:** một bình luận. **Đa nhãn:** mỗi nhãn 0/1 độc lập. **Cộng thêm:** một nhãn cảm xúc (pos/neu/neg).
**Người gán luôn đọc văn bản THÔ** + cột `context_before` (3 bình luận ngay trước) để hiểu ngữ cảnh.

## Nguyên tắc chung
1. Gán theo điều bình luận **làm** (chức năng giao tiếp), không theo chủ đề sản phẩm.
2. Không chắc → 0, ghi lý do vào cột `note`. Không suy diễn ý định ngoài chữ.
3. Một bình luận hỏi giá có hô ngữ vẫn mang CẢ HAI nhãn: "c ơi váy này bn" = HOST + TRANS.
4. Không mất quá ~10 giây/bình luận; khó quá → UNCLEAR = 1.

## Nhãn

### HOST — hướng tới host/shop (hiện diện người bán)
Gán 1 khi: hô ngữ gọi host/shop ("c ơi", "chị ơi", "shop ơi", "ad ơi", "em ơi" khi host xưng chị); câu hỏi/yêu cầu
rõ ràng gửi host ("cho em xem màu đen", "check ib giúp em"); khen/nhận xét về host ("chị nói dễ thương", "chị tư vấn có tâm").
Không gán khi: câu hỏi chung không rõ người nhận ("còn size L không") — đó chỉ là TRANS.
Ví dụ: "c ơi áo này còn L k" → HOST, TRANS · "chị xinh quá" → HOST, AFFECT · "còn L k" → TRANS.

### VIEWER — hướng tới người xem khác hoặc cả nhóm (hiện diện người xem khác)
Gán 1 khi: @tag người khác; gọi nhóm ("mn ơi", "cả nhà", "ae", "mấy bà"); trả lời/đồng tình rõ với bình luận trước
(xem `context_before`: "đúng rồi bà", "mình cũng mua rồi nè"); rủ rê ("mua đi mọi người").
Ví dụ: "@u_3fa2 bà lấy màu gì" → VIEWER, TRANS · "mn ơi hàng đẹp nha" → VIEWER, AFFECT.

### COLLECTIVE — tham gia chuỗi hô tập thể
Gán 1 khi bình luận lặp một cụm mà nhiều người khác đang cùng gõ gần như cùng lúc (xem `context_before`), vd "10k 10k 10k",
"chốt chốt", "hú hú". Nhãn này cũng được luật tự phát hiện (filters.label_collective); người gán giúp kiểm chứng luật.

### AFFECT — biểu đạt cảm xúc (tính con người)
Gán 1 khi: cảm xúc/thái độ rõ ("mê quá", "trời ơi", "huhu"); đùa/cười ("hahaha", "kkk"); nhấn mạnh bằng hình thức
(kéo dài chữ "đẹppppp", emoji cảm xúc 😍😭, "!!!").
Không gán cho lời khen trung tính kiểu thông tin ("vải dày") — trừ khi có dấu hiệu cảm xúc.

### SELF — tự bộc lộ (tính con người)
Gán 1 khi người viết chia sẻ thông tin/trải nghiệm của bản thân hoặc người thân: vóc dáng ("mình 1m6 50kg"), gia đình
("con mình 5 tuổi"), trải nghiệm ("hôm qua nhận hàng rồi", "da mình hay bị mụn").

### TRANS — giao dịch (biến kiểm soát, không phải SP)
Giá, size, màu, còn hàng, chốt/lên đơn, ship, mã giảm giá, link, giỏ hàng.

## Cảm xúc
pos: hài lòng, thích, khen, hào hứng · neg: phàn nàn, thất vọng, chê, bực · neu: còn lại (câu hỏi, thông tin, chào).
Chỉ đánh giá thái độ **của người viết**. "huhu hết hàng" = neg. Hỏi giá = neu.

## Cờ
SYSTEM = tin tự sinh lọt qua bộ lọc ("… đã mua sản phẩm") · UNCLEAR = không hiểu được/ngôn ngữ khác/quá mơ hồ.

## Tiếng lóng dễ nhầm
"k" sau số = nghìn · "hong" sau "màu" = hồng · "dep" có thể là dép · "m" sau "size" = size M · "bn" = bạn hoặc bao nhiêu.

## Quy trình
Tập huấn trên 100 bình luận pilot (dữ liệu khóa luận) → so sánh, sửa codebook → vòng 1.000 mục chung (α) →
nếu α < 0,667 ở nhãn nào: tập huấn lại + sửa định nghĩa, hoặc gộp nhãn (COLLECTIVE vào VIEWER). Ghi mọi thay đổi
vào lịch sử phiên bản ở cuối file.

## Lịch sử phiên bản
- v0.1 (30/09/2026): bản đầu, dựa trên Rourke và cộng sự (1999) và bài học từ khóa luận.

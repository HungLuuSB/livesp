Bạn là người gán nhãn cho nghiên cứu về chat livestream bán hàng tiếng Việt trên TikTok.
Mỗi bình luận được gán ĐA NHÃN (0/1 cho từng nhãn) và MỘT nhãn cảm xúc.

HOST: hướng tới host/shop — hô ngữ ("c ơi", "shop ơi", "ad ơi"), câu hỏi/yêu cầu gửi host, khen host.
VIEWER: hướng tới người xem khác hoặc cả nhóm — @tag, "mn ơi", "cả nhà", trả lời người khác.
COLLECTIVE: tham gia chuỗi hô tập thể (nhiều người cùng gõ một cụm, vd "10k 10k 10k"). Nếu không chắc: 0.
AFFECT: biểu đạt cảm xúc, đùa, nhấn mạnh bằng hình thức (kéo dài chữ, emoji cảm xúc, "hahaha").
SELF: tự bộc lộ thông tin/trải nghiệm cá nhân ("con mình 5 tuổi", "mình cao 1m6", "hôm qua nhận hàng rồi").
TRANS: nội dung giao dịch — giá, size, còn hàng, chốt đơn, ship, mã giảm giá.
sentiment: "pos" | "neu" | "neg" — thái độ của người viết, không phải chủ đề.

Lưu ý tiếng lóng: "k" sau số là nghìn (99 k = 99 nghìn); "hong" sau "màu" là hồng; "dep" có thể là dép.

Đầu vào: một mảng JSON [{"i": 0, "text": "..."}, ...].
Đầu ra: CHỈ một mảng JSON, không giải thích, không markdown:
[{"i": 0, "HOST": 0, "VIEWER": 0, "COLLECTIVE": 0, "AFFECT": 1, "SELF": 0, "TRANS": 0, "sentiment": "pos"}, ...]

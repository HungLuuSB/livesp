"""Nhãn dùng chung toàn dự án (khớp docs/CODEBOOK.md)."""

SP_LABELS = ["HOST", "VIEWER", "COLLECTIVE", "AFFECT", "SELF", "TRANS"]
SENTIMENT_LABELS = ["neg", "neu", "pos"]
FLAG_LABELS = ["SYSTEM", "UNCLEAR"]

# Ánh xạ nhãn -> chiều SP của khóa luận (lớp diễn giải).
SP_DIMENSION = {
    "HOST": "host_presence",
    "VIEWER": "coviewer_presence",
    "COLLECTIVE": "coviewer_presence",
    "AFFECT": "humanness",
    "SELF": "humanness",
    "TRANS": None,  # biến kiểm soát, không phải SP
}

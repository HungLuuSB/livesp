---
description: Làm task tiếp theo chưa đánh dấu trong docs/CLAUDE_CODE_TASKS.md
---
Đọc docs/CLAUDE_CODE_TASKS.md và tìm task đầu tiên còn `- [ ]`.
1. Nhắc lại mục tiêu và điều kiện "Xong khi" của task đó.
2. Đề xuất kế hoạch ngắn (các file sẽ sửa, lệnh sẽ chạy) rồi DỪNG, chờ tôi duyệt.
3. Sau khi tôi duyệt và bạn làm xong: chạy `make test`, đổi checkbox thành `- [x]`,
   tóm tắt thay đổi trong 5 dòng.
4. Nếu `make test` qua: `git add -A`, kiểm tra danh sách file staged KHÔNG có `.env`, `data/`, `results/`,
   `models/`, `configs/channels.csv`, rồi commit (message tiếng Việt, dòng đầu ≤ 72 ký tự, có số Task)
   và `git push`. Nếu test đỏ hoặc có file nhạy cảm: KHÔNG commit/push, báo tôi.
Tuân thủ mọi quy tắc trong CLAUDE.md, đặc biệt phần "Toàn vẹn nghiên cứu" và "Quyền riêng tư".

# Cài đặt: WSL 2 + VS Code + Claude Code cho dự án livesp

Nguồn chính thức: https://code.claude.com/docs/en/setup và https://code.claude.com/docs/en/vs-code (kiểm tra lại khi có
phiên bản mới — giao diện và tên lệnh có thể thay đổi).

## 1. Phía Windows
1. PowerShell (Admin): `wsl --install -d Ubuntu`, khởi động lại. Kiểm tra `wsl -l -v` → cột VERSION = 2.
2. Cài driver NVIDIA mới nhất cho Windows. KHÔNG cài driver Linux bên trong WSL. Trong Ubuntu gõ `nvidia-smi` phải thấy GPU.
3. Chép `scripts/wsl/wslconfig.example` thành `C:\Users\<tên>\.wslconfig`, chỉnh RAM/CPU, rồi `wsl --shutdown`.
4. Trong thời gian thu dữ liệu: Settings → System → Power → Sleep = Never; tạm hoãn khởi động lại do Windows Update.

## 2. Dự án trong Ubuntu
```bash
mkdir -p ~/projects && cd ~/projects
cp /mnt/c/Users/<tên>/Downloads/livesp.zip . && unzip livesp.zip && cd livesp
sudo cp scripts/wsl/wsl.conf.example /etc/wsl.conf      # bật systemd (xem nội dung trước khi chép)
bash scripts/setup_wsl.sh                                 # tạo .venv, cài gói, tạo .env có salt mới
source .venv/bin/activate && make test && make smoke
git init && git add -A && git commit -m "Khởi tạo livesp"
```
Để dự án trong `~/…` (ổ Linux). Đặt ở `/mnt/c/…` sẽ chậm hơn rất nhiều.
**Sao lưu dòng LIVESP_SALT trong .env** vào trình quản lý mật khẩu ngay.

## 3. VS Code
1. Cài VS Code trên Windows (bản 1.94 trở lên) và extension **WSL** (Microsoft).
2. Trong Ubuntu, tại thư mục dự án: `code .` → góc dưới trái hiện "WSL: Ubuntu".
3. Cài extension **Python** trong cửa sổ WSL đó; chọn interpreter `.venv/bin/python`.

## 4. Claude Code
Cần gói Claude Pro, Max, Team, Enterprise hoặc tài khoản Console; gói miễn phí không có Claude Code.
1. **Extension:** trong cửa sổ "WSL: Ubuntu", mở Extensions (Ctrl+Shift+X), tìm "Claude Code" (Anthropic), cài vào WSL.
   Mở một file bất kỳ → bấm biểu tượng Spark góc trên phải → Sign in qua trình duyệt.
2. **CLI (khuyến nghị thêm):** extension có sẵn CLI riêng cho khung chat, nhưng muốn gõ `claude` trong terminal
   (vd `claude --resume`) thì cài trong Ubuntu:
   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   claude --version && claude doctor
   ```
3. Claude Code tự đọc `CLAUDE.md` ở gốc dự án (quy tắc, lệnh, ràng buộc nghiên cứu). `.claude/settings.json` chặn đọc `.env`.
   `.claude/commands/` có sẵn `/next-task` và `/check`.

## 5. Cách làm việc hằng ngày
- Mỗi task: gõ `/next-task` (hoặc `/plan <mô tả>`). Claude lập kế hoạch → bạn sửa/duyệt → Claude làm.
- Để chế độ **Manual** khi Claude sửa `src/` để xem diff trước khi chấp nhận; chế độ tự động chỉ dùng cho việc vặt.
- Trỏ file bằng `@` (vd `@src/livesp/preprocess/teencode.py`); bôi đen code rồi Alt+K để chèn tham chiếu dòng.
- Sửa sai → dùng nút rewind (checkpoint) trên tin nhắn để tua code về trước đó.
- Mỗi task một cuộc hội thoại mới cho gọn ngữ cảnh; hội thoại dài thì `/compact`.
- Xong task: `make test` → xem `git diff` → commit. Không để Claude tự push.
- Không dán nội dung `.env`, salt hay khóa API vào khung chat.

## 6. Thu dữ liệu 24/7
- Nhanh: `tmux new -s cap` → `make capture` → Ctrl+B rồi D để tách. Xem lại: `tmux attach -t cap`.
- Bền hơn: systemd service (hướng dẫn ở đầu `scripts/wsl/livesp-capture.service`). Log: `journalctl --user -u livesp-capture -f`.
- Kiểm tra máy có ngủ: `data/raw/_heartbeat.json` cập nhật mỗi phút.
- Giữ một cửa sổ Windows Terminal mở vào Ubuntu nếu thấy WSL tự tắt khi rảnh; kiểm tra bằng `wsl --list --running`.

## 7. Sự cố thường gặp
| Triệu chứng | Cách xử lý |
| --- | --- |
| Không thấy biểu tượng Spark | Mở một file (không chỉ thư mục); Developer: Reload Window; kiểm tra Workspace Trust |
| `claude: command not found` | Mở terminal mới; kiểm tra PATH có `~/.local/bin`; chạy `claude doctor` |
| torch không thấy GPU | `nvidia-smi` trong WSL; cập nhật driver phía Windows; chọn lại lệnh cài torch tại pytorch.org |
| Mọi thứ chậm | Dự án đang ở `/mnt/c` → chuyển vào `~/projects` |
| CUDA out of memory | batch 16 trong configs/experiment.yaml cho MỌI điều kiện của mô hình đó |
| Recorder ngừng ghi đêm qua | Xem `_heartbeat.json`; kiểm tra chế độ ngủ của Windows và `journalctl` |

#!/usr/bin/env bash
# Cài môi trường trên WSL2 Ubuntu. Chạy từ thư mục dự án:  bash scripts/setup_wsl.sh   (thêm --no-gpu nếu không có GPU)
set -euo pipefail
cd "$(dirname "$0")/.."
case "$PWD" in /mnt/*) echo "CẢNH BÁO: dự án đang ở ổ Windows ($PWD). Nên chuyển vào ~/projects để nhanh hơn."; esac
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev build-essential git tmux unzip openjdk-17-jre-headless
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -e ".[dev,stats,capture]"
pip install -e ".[nlp]" || echo "Cảnh báo: gói nlp lỗi — chỉ cần khi dùng underthesea/VnCoreNLP"
if [[ "${1:-}" != "--no-gpu" ]]; then
  # Bản torch trên PyPI cho Linux đã kèm CUDA. Nếu check_env báo không thấy GPU, chọn lệnh đúng tại pytorch.org.
  pip install -e ".[gpu]"
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  salt=$(python -c 'import secrets; print(secrets.token_hex(32))')
  sed -i "s/^LIVESP_SALT=.*/LIVESP_SALT=${salt}/" .env
  sed -i "s#/home/YOUR_USER#${HOME}#" .env
  echo ">>> Đã tạo .env với salt mới. SAO LƯU dòng LIVESP_SALT vào trình quản lý mật khẩu NGAY."
fi
[[ -f configs/channels.csv ]] || cp configs/channels.example.csv configs/channels.csv
python scripts/check_env.py
echo ">>> Xong. Tiếp theo: source .venv/bin/activate && make test && make smoke"

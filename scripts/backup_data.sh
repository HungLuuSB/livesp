#!/usr/bin/env bash
# Sao lưu data/ và configs/channels.csv sang ổ vật lý KHÁC (mặc định D: = HDD; ổ ảo WSL nằm trên C: = SSD).
# Mất điện có thể làm hỏng ổ ảo ext4.vhdx của WSL -> bản trên D: là đường lui.
#
# Nguyên tắc:
# - KHÔNG BAO GIỜ xóa ở đích (không --delete).
# - JSONL thô chỉ ghi nối thêm -> rsync --append: bản sao lưu chỉ được NỐI THÊM, nếu file gốc ngắn hơn
#   (bị cắt cụt do hỏng ổ) thì giữ nguyên bản sao lưu.
# - File khác (nhãn, cấu hình kênh...) bị thay đổi -> bản cũ được giữ trong _versions/<thời điểm>/.
# - Ghi data/raw/_last_backup.json để scripts/capture_status.py cảnh báo khi sao lưu bị trễ.
#
# Chạy tay:  bash scripts/backup_data.sh [thư_mục_đích]      (mặc định /mnt/d/livesp_backup)
# Tự động:   scripts/wsl/livesp-backup.timer (mỗi 15 phút)
set -euo pipefail

PROJECT="${LIVESP_PROJECT:-$(cd "$(dirname "$0")/.." && pwd)}"
DEST="${1:-${LIVESP_BACKUP_DIR:-/mnt/d/livesp_backup}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RSYNC=(rsync -rt --no-perms --no-owner --no-group --exclude='.*.tmp')

mkdir -p "$DEST/data/raw" "$DEST/configs"

# 1) JSONL (dữ liệu thô + _incidents.jsonl): chỉ nối thêm
"${RSYNC[@]}" --append --include='*/' --include='*.jsonl' --include='*.jsonl.gz' --exclude='*' \
    "$PROJECT/data/raw/" "$DEST/data/raw/"

# 2) Phần còn lại của data/ (trừ dữ liệu dẫn xuất và file trạng thái đổi liên tục): giữ phiên bản cũ
"${RSYNC[@]}" --backup --backup-dir="$DEST/_versions/$STAMP/data" \
    --exclude='raw/**.jsonl' --exclude='raw/**.jsonl.gz' --exclude='interim/' \
    --exclude='raw/_heartbeat.json' --exclude='raw/_quota.json' --exclude='raw/_last_backup.json' \
    "$PROJECT/data/" "$DEST/data/"

# 3) Danh sách kênh thật (không có trong git)
if [ -f "$PROJECT/configs/channels.csv" ]; then
    "${RSYNC[@]}" --backup --backup-dir="$DEST/_versions/$STAMP/configs" \
        "$PROJECT/configs/channels.csv" "$DEST/configs/"
fi

N_FILES=$(find "$DEST/data/raw" -name '*.jsonl' | wc -l)
SIZE=$(du -sh "$DEST" | cut -f1)
TMP="$PROJECT/data/raw/._last_backup.json.tmp"
printf '{"ts": %s, "dest": "%s", "n_jsonl": %s, "size": "%s"}\n' "$(date +%s)" "$DEST" "$N_FILES" "$SIZE" > "$TMP"
sync "$TMP"
mv -f "$TMP" "$PROJECT/data/raw/_last_backup.json"
echo "Sao lưu xong -> $DEST ($N_FILES file JSONL, $SIZE)"

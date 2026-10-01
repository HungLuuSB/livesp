"""Ẩn danh ngay lúc ghi: băm định danh bằng HMAC có salt bí mật, che số điện thoại/email.

Nguyên tắc: không có username, nickname hay avatar nào được ghi xuống đĩa.
Salt nằm trong .env (LIVESP_SALT) và KHÔNG được commit. Mất salt = không nối được dữ liệu cũ
với dữ liệu mới, nên hãy sao lưu salt ở nơi an toàn (trình quản lý mật khẩu).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

SALT_ENV = "LIVESP_SALT"

# Handle TikTok: chữ, số, dấu chấm, gạch dưới; 2–24 ký tự.
MENTION_RE = re.compile(r"@([A-Za-z0-9_.]{2,24})")
# Số điện thoại Việt Nam: 0xxxxxxxxx hoặc +84xxxxxxxxx, cho phép dấu cách/chấm/gạch giữa các nhóm.
PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# Khóa trong payload thô cần bỏ hẳn (ảnh, tên hiển thị, v.v.). So khớp sau khi đổi camelCase -> snake_case.
DROP_KEYS = {
    "nickname", "nick_name", "display_id", "avatar", "avatar_thumb", "avatar_medium",
    "avatar_large", "profile_picture", "avatar_url", "bio_description", "signature",
    "sec_uid", "image", "images", "url_list", "badge_image_list",
}
# Khóa chứa định danh cần băm thay vì bỏ.
HASH_KEYS = {"unique_id", "username", "user_id", "id_str", "uid"}
# Khóa kiểu "from_user_id", "anchor_uid", "mention_user_list", "to_member_id"... cũng là định danh.
ID_OWNER_RE = re.compile(r"(user|uid|anchor|contributor|operator|owner|member)")
ID_SUFFIX_RE = re.compile(r"(id|ids|id_str|uid|user_list)$")
# Một dict có các khóa này là hồ sơ người dùng (User của TikTok) -> thu gọn thành một mã băm.
USER_MARKERS = {"display_id", "nickname", "sec_uid"}


def _snake(key: object) -> str:
    """'displayId' -> 'display_id' (betterproto to_dict trả camelCase)."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)).lower()


def _is_drop_key(k: str) -> bool:
    return k in DROP_KEYS or "avatar" in k or k.endswith("nickname")


def _is_id_key(k: str) -> bool:
    return k in HASH_KEYS or bool(ID_OWNER_RE.search(k) and ID_SUFFIX_RE.search(k))


def _user_hash(d: dict, salt: bytes) -> str | None:
    """Mã băm cho một hồ sơ người dùng: ưu tiên @handle (khớp cột user do recorder ghi), sau đó id số."""
    keys = {_snake(k): v for k, v in d.items()}
    handle = keys.get("unique_id") or keys.get("display_id") or keys.get("username")
    if handle:
        return hash_id(handle, salt)
    uid = keys.get("id") or keys.get("id_str")
    return hash_id(f"id:{uid}", salt) if uid else None


def get_salt() -> bytes:
    salt = os.environ.get(SALT_ENV)
    if not salt or len(salt) < 16:
        raise RuntimeError(
            f"Thiếu {SALT_ENV} (>= 16 ký tự) trong .env. Tạo bằng: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return salt.encode("utf-8")


def hash_id(value: object, salt: bytes | None = None, n: int = 16) -> str | None:
    """Băm một chiều, ổn định: cùng giá trị + cùng salt -> cùng mã."""
    if value is None:
        return None
    s = str(value).strip().lower().lstrip("@")
    if not s:
        return None
    salt = salt if salt is not None else get_salt()
    return hmac.new(salt, s.encode("utf-8"), hashlib.sha256).hexdigest()[:n]


def hash_mentions(text: str, salt: bytes | None = None) -> str:
    """'@lan.nguyen mua đi' -> '@u_3fa2c1d0 mua đi' (giữ được cấu trúc trả lời, bỏ danh tính)."""
    salt = salt if salt is not None else get_salt()
    return MENTION_RE.sub(lambda m: "@u_" + (hash_id(m.group(1), salt, 8) or "x"), text)


def mask_pii(text: str) -> str:
    """Che email trước (vì email có '@'), rồi số điện thoại."""
    text = EMAIL_RE.sub("<EMAIL>", text)
    text = PHONE_RE.sub("<SĐT>", text)
    return text


def scrub_payload(obj: object, salt: bytes | None = None) -> object:
    """Đi đệ quy trong payload thô.

    - Hồ sơ người dùng (dict có display_id/nickname/sec_uid) -> {"unique_id": <băm>}, bỏ mọi thứ khác.
    - Bỏ khóa ảnh/tên hiển thị; băm khóa định danh (kể cả danh sách id); che SĐT/email, băm @mention
      trong MỌI chuỗi (tin ghim, thông báo hệ thống có thể chứa bình luận).
    """
    salt = salt if salt is not None else get_salt()
    if isinstance(obj, dict):
        if USER_MARKERS & {_snake(k) for k in obj}:
            return {"unique_id": _user_hash(obj, salt)}
        out = {}
        for k, v in obj.items():
            kl = _snake(k)
            if _is_drop_key(kl):
                continue
            if _is_id_key(kl) and isinstance(v, (str, int)) and not isinstance(v, bool):
                out[k] = hash_id(v, salt)
            elif _is_id_key(kl) and isinstance(v, list) and all(isinstance(x, (str, int)) for x in v):
                out[k] = [hash_id(x, salt) for x in v]
            else:
                out[k] = scrub_payload(v, salt)
        return out
    if isinstance(obj, list):
        return [scrub_payload(x, salt) for x in obj]
    if isinstance(obj, (bytes, bytearray)):
        return None
    if isinstance(obj, str):
        return clean_comment_text(obj, salt)
    return obj


def clean_comment_text(text: str, salt: bytes | None = None) -> str:
    """Áp dụng cho MỌI bình luận trước khi ghi xuống đĩa."""
    return hash_mentions(mask_pii(text or ""), salt)

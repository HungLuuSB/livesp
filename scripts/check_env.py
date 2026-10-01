"""Kiểm tra môi trường WSL2: Python, gói, GPU/CUDA, vị trí thư mục, .env, Java (cho VnCoreNLP)."""
import importlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = lambda b: "OK " if b else "!! "  # noqa: E731
print(f"{ok(sys.version_info >= (3, 10))}Python {sys.version.split()[0]}")
print(f"{ok(not str(ROOT).startswith('/mnt/'))}Thư mục dự án: {ROOT}"
      + ("  <- đang ở ổ Windows, CHUYỂN vào ~/ để nhanh hơn nhiều" if str(ROOT).startswith("/mnt/") else ""))
for m in ["numpy", "pandas", "sklearn", "scipy", "yaml", "pyarrow", "TikTokLive", "torch", "transformers",
          "emoji", "underthesea", "py_vncorenlp", "statsmodels", "anthropic", "pytest"]:
    try:
        mod = importlib.import_module(m)
        print(f"OK  {m} {getattr(mod, '__version__', '')}")
    except Exception:
        print(f"--  {m} chưa cài (tùy chọn nếu không dùng phần tương ứng)")
try:
    import torch

    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"OK  GPU {p.name} | {p.total_memory / 2**30:.1f} GB | compute {p.major}.{p.minor} | CUDA {torch.version.cuda}")
    else:
        print("!!  torch không thấy GPU. Kiểm tra `nvidia-smi` trong WSL; driver NVIDIA chỉ cài phía Windows.")
except ImportError:
    pass
env = ROOT / ".env"
salt_ok = env.exists() and any(l.startswith("LIVESP_SALT=") and len(l.strip()) > 28 for l in env.read_text().splitlines())
print(f"{ok(salt_ok)}.env có LIVESP_SALT")
print(f"{ok(bool(shutil.which('java')))}Java (cần cho RDRSegmenter/VnCoreNLP khi dùng PhoBERT)")
free = shutil.disk_usage(ROOT).free / 2**30
print(f"{ok(free > 30)}Dung lượng trống: {free:.0f} GB")
print(f"{ok(bool(os.environ.get('HF_HOME')) or True)}HF_HOME={os.environ.get('HF_HOME', '(mặc định ~/.cache/huggingface)')}")

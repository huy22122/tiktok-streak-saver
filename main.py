import os
import sys

# Cấu hình mã hóa UTF-8 để không bị lỗi ký tự icon trên Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if os.path.exists(".env"):
    from dotenv import load_dotenv

    load_dotenv(".env")

from core.tasks import runTasks

runTasks()

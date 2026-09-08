"""
login_helper.py
Công cụ tự động đăng nhập TikTok, trích xuất Cookie và tạo file cấu hình .env / GitHub Secrets
"""

import os
import sys

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import json
import time
from playwright.sync_api import sync_playwright
from utils.config import sanitize_cookies

def main():
    print("=" * 65)
    print("🔥 CÔNG CỤ TỰ ĐỘNG ĐĂNG NHẬP VÀ LẤY COOKIE TIKTOK STREAK 🔥")
    print("=" * 65)
    print("\n1. Trình duyệt Chrome sẽ tự động mở trang đăng nhập TikTok.")
    print("2. Bạn hãy đăng nhập tài khoản TikTok của mình (quét mã QR hoặc đăng nhập mật khẩu/SMS/Google).")
    print("3. Sau khi đăng nhập thành công, công cụ sẽ tự động phát hiện và trích xuất Cookie!")
    print("-" * 65)

    input("\n👉 Nhấn [Enter] để mở trình duyệt đăng nhập...")

    # Cấu hình mở trình duyệt hiển thị (non-headless)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
        )
        page = context.new_page()

        print("\n⏳ Đang mở trang https://www.tiktok.com/login ...")
        page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")

        print("\n👉 Vui lòng ĐĂNG NHẬP trên cửa sổ trình duyệt vừa mở...")
        print("⏳ Đang đợi bạn đăng nhập thành công...")

        logged_in = False
        cookies_list = []
        user_id = "acc1"

        # Lặp kiểm tra phiên đăng nhập (tối đa 5 phút)
        start_time = time.time()
        while time.time() - start_time < 300:
            time.sleep(2)
            raw_cookies = context.cookies()
            cleaned = sanitize_cookies(raw_cookies)
            
            # Kiểm tra xem đã có sessionid của tiktok chưa
            has_session = any(c.get("name") == "sessionid" and c.get("value") for c in cleaned)
            current_url = page.url.lower()

            if has_session and "/login" not in current_url:
                logged_in = True
                cookies_list = cleaned
                print("\n🎉 ĐĂNG NHẬP TIKTOK THÀNH CÔNG!")
                break

        if not logged_in:
            print("\n❌ Hết thời gian chờ đăng nhập (5 phút) hoặc chưa hoàn tất đăng nhập. Vui lòng thử lại!")
            browser.close()
            return

        # Đóng trình duyệt sau khi đã lấy được cookie
        browser.close()

    # Nhập danh sách bạn bè và nhóm cần rep chuỗi
    print("\n" + "=" * 65)
    print("📋 THIẾT LẬP DANH SÁCH BẠN BÈ & NHÓM CHAT CẦN GIỮ CHUỖI TIKTOK")
    print("=" * 65)
    print("Nhập tên hiển thị bạn bè hoặc Tên nhóm chat TikTok (cách nhau bằng dấu phẩy).")
    print("Ví dụ: Huy, 106267-K24, Nhóm bạn thân, mai phuong.")
    
    target_input = input("\n👉 Nhập danh sách bạn bè / nhóm: ").strip()
    if not target_input:
        target_list = ["Huy"]
        print("⚠️ Bạn chưa nhập tên, đã đặt mặc định là: ['Huy']")
    else:
        target_list = [t.strip() for t in target_input.split(",") if t.strip()]

    # Tạo JSON cấu hình
    tasks_data = [
        {
            "username": "Tài khoản của tôi",
            "unique_id": user_id,
            "targets": target_list,
        }
    ]

    tasks_json_str = json.dumps(tasks_data, ensure_ascii=False)
    cookies_json_str = json.dumps(cookies_list, ensure_ascii=False)

    # Ghi đè vào file .env trên máy để có thể chạy thử ngay
    env_content = f"""# Cấu hình tự động tạo bởi login_helper.py
TASKS={tasks_json_str}
COOKIES_ACC1={cookies_json_str}
MESSAGE_TEMPLATE=[RANDOM_MESSAGE]
LOG_LEVEL=DEBUG
BROWSER_TIMEOUT=120000
TASK_RETRY_TIMES=3
"""
    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n" + "✅" * 30)
    print("🎉 ĐÃ TỰ ĐỘNG TẠO FILE .ENV THÀNH CÔNG CHO MÁY TÍNH CỦA BẠN!")
    print("Bây giờ bạn có thể chạy file '2_Chay_Rep_Chuoi_Thu_Nghiem.bat' để test ngay!")
    print("✅" * 30)

    # In thông tin sẵn sàng copy lên GitHub Secrets
    print("\n" + "=" * 65)
    print("☁️ THÔNG TIN ĐỂ CẤU HÌNH GITHUB SECRETS (CHẠY FREE 24/7 CLOUD)")
    print("=" * 65)
    print("Hãy vào Repo GitHub -> Settings -> Secrets and variables -> Actions:")
    print("\n1. Tạo Secret thứ nhất:")
    print("   - Name : TASKS")
    print(f"   - Value: {tasks_json_str}")
    print("\n2. Tạo Secret thứ hai:")
    print("   - Name : COOKIES_ACC1")
    print(f"   - Value: {cookies_json_str}")
    print("=" * 65)

    input("\n👉 Nhấn [Enter] để kết thúc...")


if __name__ == "__main__":
    main()

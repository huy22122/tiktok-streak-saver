import os, sys
import subprocess
import traceback
from playwright.sync_api import sync_playwright
from utils.config import DEBUG, get_environment, Environment

PLAYWRIGHT_BROWSERS_PATH = "../chrome"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

def install_browser():
    """
    Cài đặt Chromium cho Playwright
    """
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
        print("Cài đặt trình duyệt hoàn tất, vui lòng chạy lại chương trình.")
    except subprocess.CalledProcessError as e:
        print(f"Lỗi khi cài đặt trình duyệt: {e}")


def get_browser():
    """
    Khởi động trình duyệt Playwright với các cờ chống phát hiện bot và tối ưu tài nguyên
    :return: (playwright, browser)
    """

    headless = True

    env = get_environment()
    if env == Environment.LOCAL:
        # Nếu đường dẫn ../chrome tồn tại thì dùng, ngược lại dùng mặc định của hệ thống
        custom_path = os.path.abspath(os.path.join(os.path.dirname(__file__), PLAYWRIGHT_BROWSERS_PATH))
        if os.path.exists(custom_path):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = custom_path
        if DEBUG:
            headless = False
    elif env == Environment.PACKED:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.abspath(
            os.path.join(os.path.dirname(sys.executable), PLAYWRIGHT_BROWSERS_PATH)
        )

    # Cấu hình chống phát hiện bot và tiết kiệm RAM/CPU cho TikTok
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--ignore-certificate-errors",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--mute-audio",
    ]

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=headless,
            args=launch_args
        )
        return playwright, browser
    except Exception as e:
        if "Executable doesn't exist" in str(e) and env != Environment.GITHUBACTION:
            print("Trình duyệt Chromium chưa được cài đặt!")
            install_browser()
            sys.exit(1)
        else:
            traceback.print_exc()
            raise

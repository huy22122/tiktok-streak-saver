import os, sys
from enum import Enum
import json
import logging
from utils.logger import setup_logger
from utils import norm

logger = setup_logger(level=logging.DEBUG)

"""
是否启用调试模式
更详细的日志打印，浏览器操作可视化等
"""
DEBUG = True
config = None
userData = None


class Environment(Enum):
    GITHUBACTION = "GITHUB_ACTION"  # GitHub Action 运行
    LOCAL = "LOCAL"  # 本地代码运行
    PACKED = "PACKED"  # PyInstaller 打包运行

    def __str__(self):
        return self.value


def get_environment():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Environment.PACKED
    elif os.getenv("GITHUB_ACTIONS") == "true":
        return Environment.GITHUBACTION
    else:
        return Environment.LOCAL


def get_config():
    """
    Lấy thông tin cấu hình từ biến môi trường
    :return: dict cấu hình
    """
    global config

    if config:
        return config

    # Đọc cấu hình từ config.json nếu có (để đồng bộ web GitHub)
    file_config = {}
    config_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
    if not os.path.exists(config_file_path):
        config_file_path = "config.json"
    if os.path.exists(config_file_path):
        try:
            with open(config_file_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
        except Exception as e:
            logger.warning(f"Không thể đọc config.json: {e}")

    config = {
        "proxyAddress": os.getenv("PROXY_ADDRESS", file_config.get("proxy_address", "")),
        "streakLanguage": os.getenv("STREAK_LANGUAGE", file_config.get("streak_language", "vi")),
        "messageTemplate": os.getenv(
            "MESSAGE_TEMPLATE",
            file_config.get("message_template", "[RANDOM_MESSAGE]"),
        ),
        "hitokotoTypes": json.loads(
            os.getenv("HITOKOTO_TYPES", '["文学","影视","诗词","哲学"]')
        ),
        "browserTimeout": int(
            os.getenv("BROWSER_TIMEOUT", str(file_config.get("browser_timeout", "120000")))
        ),
        "friendListTimeout": int(
            os.getenv("FRIEND_LIST_WAIT_TIME", "3000")
        ),
        "randomDelayMinutes": int(
            os.getenv("RANDOM_DELAY_MINUTES", str(file_config.get("random_delay_minutes", "0")))
        ),
        "taskRetryTimes": int(os.getenv("TASK_RETRY_TIMES", str(file_config.get("task_retry_times", "3")))),
        "logLevel": os.getenv("LOG_LEVEL", "DEBUG"),
    }

    return config


def sanitize_cookies(cookies):
    """
    Làm sạch danh sách Cookie để tương thích hoàn toàn với Playwright và Chrome DevTools Protocol.
    Loại bỏ các cookie rác (Google, YouTube OAuth), chuẩn hóa domain và trường expires.
    """
    cleaned_cookies = []
    allowed_keys = {"name", "value", "url", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}

    for c in cookies:
        if not isinstance(c, dict):
            continue

        name = str(c.get("name", "")).strip()
        value = str(c.get("value", ""))
        domain = str(c.get("domain", "")).strip().lower()

        if not name or not value:
            continue

        # Chỉ giữ lại các cookie thuộc tên miền TikTok
        if "tiktok.com" not in domain and not domain.endswith("tiktok.com"):
            continue

        # Cookie có tiền tố __Host- không được phép chứa thuộc tính domain
        if name.startswith("__Host-"):
            continue

        cookie = {
            "name": name,
            "value": value,
            "domain": ".tiktok.com",
            "path": "/",
        }

        # Xử lý expires: phải là số nguyên dương (timestamp), bỏ qua nếu <= 0
        expires = c.get("expires")
        if expires is not None:
            try:
                exp_int = int(float(expires))
                if exp_int > 0:
                    cookie["expires"] = exp_int
            except (ValueError, TypeError):
                pass

        if "httpOnly" in c and isinstance(c["httpOnly"], bool):
            cookie["httpOnly"] = c["httpOnly"]

        if "secure" in c and isinstance(c["secure"], bool):
            cookie["secure"] = c["secure"]

        # Xử lý sameSite chuẩn: "Strict", "Lax", "None"
        same_site = c.get("sameSite")
        if same_site:
            same_site_str = str(same_site).capitalize()
            if same_site_str in ["Strict", "Lax", "None"]:
                cookie["sameSite"] = same_site_str
                if same_site_str == "None":
                    cookie["secure"] = True

        cleaned_cookies.append(cookie)

    return cleaned_cookies


def get_userData():
    """
    Lấy dữ liệu danh sách tài khoản và bạn bè cần giữ chuỗi
    :return: danh sách user data
    """
    global userData

    if userData:
        return userData

    tasks_raw = os.getenv("TASKS", "").strip()
    if (tasks_raw.startswith("'") and tasks_raw.endswith("'")) or (tasks_raw.startswith('"') and tasks_raw.endswith('"')):
        tasks_raw = tasks_raw[1:-1].strip()

    tasks = []
    if tasks_raw:
        try:
            tasks = json.loads(tasks_raw)
        except json.JSONDecodeError:
            try:
                tasks = json.loads(tasks_raw.replace(r'\"', '"'))
            except Exception:
                logger.error("Biến môi trường TASKS không đúng định dạng JSON!")
                tasks = []

    # Nếu biến môi trường TASKS rỗng hoặc chưa set, đọc từ file config.json
    if not tasks:
        config_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
        if not os.path.exists(config_file_path):
            config_file_path = "config.json"
        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if "account" in cfg:
                        tasks = [cfg["account"]]
            except Exception as e:
                logger.warning(f"Lỗi nạp tasks từ config.json: {e}")

    # Đồng bộ danh sách mục tiêu mới nhất từ file config.json nếu có
    try:
        config_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
        if not os.path.exists(config_file_path):
            config_file_path = "config.json"
        if os.path.exists(config_file_path):
            with open(config_file_path, "r", encoding="utf-8") as f:
                cfg_sync = json.load(f)
                if "account" in cfg_sync and "targets" in cfg_sync["account"]:
                    for tsk in tasks:
                        tsk["targets"] = cfg_sync["account"]["targets"]
    except Exception:
        pass

    if not tasks:
        tasks = [{"username": "Tài khoản TikTok", "unique_id": "acc1", "targets": []}]

    userData = []

    for task in tasks:
        username = task.get("username", "Tài khoản TikTok")
        unique_id = task.get("unique_id")
        if not unique_id:
            logger.warning(f"Tài khoản '{username}' thiếu trường unique_id, đã bỏ qua.")
            continue

        # Tìm cookies trong biến môi trường với các biến thể hoa/thường
        keys_to_try = [
            f"COOKIES_{unique_id}".upper(),
            f"COOKIES_{unique_id}".lower(),
            f"COOKIES_{unique_id}",
            f"COOKIES_{unique_id.replace('-', '_')}".upper(),
            f"COOKIES_{unique_id.replace('-', '_')}",
        ]

        cookies_str = ""
        matched_key = ""
        for k in keys_to_try:
            val = os.getenv(k, "")
            if val:
                cookies_str = val
                matched_key = k
                break

        if not cookies_str:
            logger.warning(
                f"Tài khoản '{username}' ({unique_id}) thiếu biến môi trường cookies ({keys_to_try[0]}), đã bỏ qua."
            )
            continue

        try:
            # Thử decode nếu có ký tự thoát
            if "\\" in cookies_str:
                try:
                    cookies_str = cookies_str.encode("utf-8").decode("unicode_escape")
                except Exception:
                    pass
            cookies = json.loads(cookies_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Cookie của tài khoản '{username}' ({matched_key}) không đúng định dạng JSON: {e}")
            continue

        raw_targets = task.get("targets", [])
        # Chuẩn hóa danh sách mục tiêu bạn bè
        targets = []
        for t in raw_targets:
            t_str = norm(str(t))
            if t_str:
                targets.append(t_str)

        userData.append(
            {
                "unique_id": unique_id,
                "username": username,
                "cookies": sanitize_cookies(cookies),
                "targets": targets,
            }
        )

    return userData

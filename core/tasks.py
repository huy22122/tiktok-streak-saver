import os
import time
import random
import traceback
from playwright.sync_api import Response
from utils.logger import setup_logger
from utils.config import get_config, get_userData
from utils import norm
from core.msg_builder import build_message, build_message_with_openai
from core.browser import get_browser, DEFAULT_USER_AGENT

config = get_config()
userData = get_userData()
logger = setup_logger(level=config.get("logLevel", "DEBUG"))
userIDDict = {}

# TikTok Web Message URL
TIKTOK_MESSAGES_URL = "https://www.tiktok.com/messages"

# Danh sách bộ chọn hội thoại (cả bạn bè cá nhân và nhóm chat) trên TikTok Web
CONVERSATION_SELECTORS = [
    'span[class*="SpanNicknameText"]',
    'p[class*="PInfoNickname"]',
    '[class*="Nickname"]',
    '[class*="GroupName"]',
    '[class*="GroupTitle"]',
    '[class*="PTitle"]',
    '[class*="SpanTitle"]',
    '[data-e2e="chat-item"]',
]

CHAT_EDITOR_SELECTORS = [
    'div.public-DraftEditor-content',
    'div[contenteditable="true"]',
    'div[role="textbox"]',
    '[data-e2e="chat-input"]',
    'div[class*="DraftEditor"]',
    'div[class*="editor"]',
    'textarea',
]

SEND_BUTTON_SELECTORS = [
    '[data-e2e="message-send-btn"]',
    'button[aria-label="Send"]',
    'button[aria-label="Gửi"]',
    'button[type="submit"]',
    'div[class*="SendButton"]',
]


def handle_response(response: Response):
    """
    Lắng nghe API TikTok để thu thập nickname/ID/Group info nếu có
    """
    global userIDDict
    url = response.url
    if any(keyword in url for keyword in ["im/user/info", "im/conversation", "user/detail", "api/user", "im/group"]):
        try:
            if "application/json" in response.headers.get("content-type", ""):
                json_data = response.json()
                data_list = json_data.get("data", [])
                if isinstance(data_list, dict):
                    data_list = [data_list]
                for item in data_list:
                    if not isinstance(item, dict):
                        continue
                    uid = str(item.get("uid", item.get("id", "")))
                    sec_uid = item.get("sec_uid", "")
                    unique_id = item.get("unique_id", item.get("uniqueId", ""))
                    nickname = norm(item.get("nickname", item.get("name", "")))
                    remark_name = norm(item.get("remark_name", nickname))
                    if nickname:
                        userIDDict[nickname] = [uid, unique_id, sec_uid, nickname, remark_name]
                    if unique_id:
                        userIDDict[unique_id] = [uid, unique_id, sec_uid, nickname, remark_name]
        except Exception:
            pass


def retry_operation(name, operation, retries=3, delay=2, *args, **kwargs):
    """
    Thực thi thao tác có cơ chế thử lại (retry)
    """
    for attempt in range(retries):
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"{name} thất bại, đang thử lại lần {attempt + 1}/{retries}, lỗi: {e}")
                time.sleep(delay)
            else:
                logger.error(f"{name} thất bại sau {retries} lần thử, lỗi: {e}")
                raise


def dismiss_popups(page):
    """
    Tự động đóng popup cookie/thông báo của TikTok
    """
    popup_button_texts = [
        "Decline all", "Decline optional cookies", "Reject all", "Từ chối",
        "Accept all", "Allow all cookies", "Chấp nhận tất cả", "Cho phép",
        "Not now", "Để sau", "Không phải bây giờ", "Cancel", "Hủy",
        "Close", "Đóng"
    ]

    for text in popup_button_texts:
        try:
            button = page.locator(f'button:has-text("{text}")').first
            if button.is_visible(timeout=300):
                logger.debug(f"Phát hiện popup, đang đóng: '{text}'")
                button.click()
                time.sleep(0.2)
                break
        except Exception:
            pass


def check_target_match(name_text: str, targets: list) -> str:
    """
    Kiểm tra tên bạn bè hoặc tên nhóm chat có khớp với danh sách targets không
    """
    norm_name = norm(name_text).lower().lstrip("@").strip()
    if not norm_name:
        return ""

    for t in targets:
        clean_t = norm(t).lower().lstrip("@").strip()
        if not clean_t:
            continue

        # 1. Khớp chính xác
        if clean_t == norm_name:
            return t

        # 2. Khớp chứa chuỗi (nếu độ dài >= 3)
        if len(norm_name) >= 3 and norm_name in clean_t:
            return t
        if len(clean_t) >= 3 and clean_t in norm_name:
            return t

    # 3. Tra cứu từ điển API đã bắt được
    if name_text in userIDDict:
        for t in targets:
            if any(t.lower() == str(v).lower() for v in userIDDict[name_text] if v):
                return t

    return ""


def find_chat_input_element(page, timeout=8000):
    """Tìm khung soạn thảo tin nhắn siêu tốc (hỗ trợ cả chat 1-1 và nhóm)"""
    start_time = time.time()
    while time.time() - start_time < (timeout / 1000):
        for sel in CHAT_EDITOR_SELECTORS:
            try:
                locator = page.locator(sel).first
                if locator.is_visible(timeout=300):
                    return locator
            except Exception:
                continue
        time.sleep(0.2)
    return None


def select_friend_conversation(page, username, targets):
    """
    Tìm và chọn từng bạn bè hoặc nhóm chat trong danh sách hội thoại TikTok (siêu tốc, hỗ trợ cuộn)
    """
    logger.info(f"[{username}] Bắt đầu tìm kiếm {len(targets)} mục tiêu: {targets}")

    found_targets = set()
    remaining_targets = set(targets)

    # Quét danh sách hội thoại và cuộn để tìm mục tiêu
    for scroll_idx in range(8):
        dismiss_popups(page)
        item_found_in_this_scroll = False

        for sel in CONVERSATION_SELECTORS:
            if len(remaining_targets) == 0:
                break
            try:
                elements = page.locator(sel).all()
                for el in elements:
                    if not el.is_visible():
                        continue
                    txt = el.inner_text().strip()
                    if not txt:
                        continue

                    matched = check_target_match(txt, list(remaining_targets))
                    if matched and matched not in found_targets:
                        found_targets.add(matched)
                        remaining_targets.remove(matched)
                        item_found_in_this_scroll = True
                        logger.info(f"[{username}] Đã tìm thấy mục tiêu: '{matched}' (Tên hiển thị: '{txt}')")
                        el.click()
                        time.sleep(0.3)
                        yield matched
                        break
            except Exception as e:
                logger.debug(f"Lỗi quét phần tử: {e}")

        if len(remaining_targets) == 0:
            logger.info(f"[{username}] Đã tìm thấy tất cả mục tiêu đã cấu hình!")
            return

        if not item_found_in_this_scroll:
            # Cuộn danh sách xuống để nạp thêm các hội thoại cũ hơn
            page.mouse.wheel(0, 600)
            time.sleep(0.4)

    if len(remaining_targets) > 0:
        logger.warning(
            f"[{username}] Không tìm thấy các bạn bè/nhóm sau trong danh sách tin nhắn: {list(remaining_targets)}"
        )


def do_user_task(browser, username, cookies, targets):
    """
    Thực hiện gửi tin nhắn rep chuỗi TikTok siêu tốc cho một tài khoản
    """
    context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1280, "height": 800},
        locale="vi-VN",
        timezone_id="Asia/Ho_Chi_Minh",
    )
    context.set_default_navigation_timeout(config["browserTimeout"])
    context.set_default_timeout(config["browserTimeout"])

    page = context.new_page()
    page.on("response", handle_response)

    try:
        # Nạp Cookie an toàn vào trình duyệt
        if cookies:
            logger.debug(f"[{username}] Đang nạp {len(cookies)} cookies vào trình duyệt...")
            try:
                context.add_cookies(cookies)
            except Exception as e:
                logger.warning(f"[{username}] Nạp cookie hàng loạt gặp lỗi: {e}. Đang nạp từng cookie...")
                for c in cookies:
                    try:
                        context.add_cookies([c])
                    except Exception:
                        pass

        # Mở trang tin nhắn TikTok Web
        logger.info(f"[{username}] Đang truy cập {TIKTOK_MESSAGES_URL}...")
        retry_operation(
            f"Mở {TIKTOK_MESSAGES_URL}",
            page.goto,
            retries=config["taskRetryTimes"],
            delay=2,
            url=TIKTOK_MESSAGES_URL,
            wait_until="domcontentloaded",
        )

        # Chờ phần tử hội thoại xuất hiện siêu tốc thay vì ngủ 5s cố định
        try:
            page.wait_for_selector(
                'span[class*="SpanNicknameText"], p[class*="PInfoNickname"], [class*="Nickname"], [data-e2e="chat-item"]',
                timeout=4000
            )
        except Exception:
            time.sleep(1)

        dismiss_popups(page)

        # Kiểm tra đăng nhập
        current_url = page.url.lower()
        if "/login" in current_url:
            logger.error(
                f"❌ [{username}] Trình duyệt bị chuyển hướng về trang đăng nhập ({page.url}). "
                "Cookie TikTok của bạn đã hết hạn! Vui lòng chạy '1_Dang_Nhap_Lay_Cookie.bat' để lấy lại Cookie."
            )
            return

        logger.info(f"[{username}] Đăng nhập TikTok thành công, bắt đầu gửi tin nhắn rep chuỗi siêu tốc...")

        sent_count = 0
        for target_name in select_friend_conversation(page, username, targets):
            logger.info(f"[{username}] Đang soạn tin nhắn cho: {target_name}")

            chat_input = find_chat_input_element(page, timeout=8000)
            if not chat_input:
                logger.error(f"[{username}] Không tìm thấy khung soạn thảo tin nhắn cho '{target_name}'!")
                continue

            message = build_message(target_name=target_name)

            # Focus và gõ tin nhắn siêu tốc
            chat_input.click()
            time.sleep(0.1)

            # Gõ nội dung tin nhắn tức thì (delay=0)
            lines = message.split("\n")
            for i, line in enumerate(lines):
                chat_input.type(line, delay=0)
                if i < len(lines) - 1:
                    chat_input.press("Shift+Enter")

            time.sleep(0.1)

            # Gửi tin nhắn bằng phím Enter
            chat_input.press("Enter")

            # Fallback nút gửi (nếu phím Enter chưa kích hoạt)
            time.sleep(0.2)
            for send_btn_sel in SEND_BUTTON_SELECTORS:
                try:
                    btn = page.locator(send_btn_sel).first
                    if btn.is_visible(timeout=200):
                        btn.click()
                        break
                except Exception:
                    pass

            logger.info(f"⚡ [{username}] Đã gửi siêu tốc tới '{target_name}': \"{message}\"")
            sent_count += 1

            delay_between = random.uniform(0.3, 0.6)
            logger.debug(f"Chuyển ngay sang mục tiêu tiếp theo trong {delay_between:.1f}s...")
            time.sleep(delay_between)

        logger.info(f"🎉 [{username}] Hoàn tất! Đã gửi tin nhắn rep chuỗi thành công cho {sent_count}/{len(targets)} mục tiêu.")

    except Exception as e:
        logger.error(f"[{username}] Xảy ra lỗi trong quá trình thực hiện: {e}")
        traceback.print_exc()
    finally:
        context.close()


def runTasks():
    """
    Khởi chạy toàn bộ tiến trình cho tất cả tài khoản
    """
    users = get_userData()
    if not users:
        logger.warning("⚠️ Không tìm thấy cấu hình tài khoản nào trong TASKS!")
        return

    # Xử lý độ trễ ngẫu nhiên nếu được cấu hình
    skip_delay = os.getenv("SKIP_RANDOM_DELAY", "false").lower() in ["true", "1", "yes"]
    raw_delay = os.getenv("RANDOM_DELAY_MINUTES", "").strip()
    if not raw_delay:
        raw_delay = str(config.get("randomDelayMinutes", "0"))
    try:
        max_delay_min = int(raw_delay)
    except ValueError:
        max_delay_min = 0

    if not skip_delay and max_delay_min > 0:
        delay_sec = random.randint(15, max_delay_min * 60)
        delay_m = delay_sec // 60
        delay_s = delay_sec % 60
        logger.info(f"⏳ Kích hoạt độ trễ ngẫu nhiên: Chờ {delay_m} phút {delay_s} giây trước khi gửi (tránh gửi vào giờ cố định)...")
        time.sleep(delay_sec)
    else:
        logger.info("⚡ Chế độ siêu tốc (0s trễ ngẫu nhiên): Bắt đầu gửi ngay lập tức!")

    playwright, browser = get_browser()
    try:
        logger.info("==================================================")
        logger.info("🔥 Bắt đầu tiến trình TikTok Streak Saver (Rep Chuỗi Bạn Bè & Nhóm) 🔥")
        logger.info(f"Tổng số tài khoản cần xử lý: {len(users)}")
        logger.info("==================================================")

        for user in users:
            unique_id = user["unique_id"]
            username = user.get("username", unique_id)
            cookies = user["cookies"]
            targets = user["targets"]

            logger.info(f"--- Bắt đầu xử lý tài khoản: {username} (ID: {unique_id}) ---")
            do_user_task(browser, username, cookies, targets)
            logger.info(f"--- Kết thúc xử lý tài khoản: {username} ---\n")

    finally:
        browser.close()
        playwright.stop()
        logger.info("Đã đóng trình duyệt và hoàn tất toàn bộ tiến trình.")

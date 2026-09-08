"""
app_manager.py
Backend máy chủ quản lý cục bộ cho TikTok Streak Saver
Cung cấp REST API đồng bộ 2 chiều với file .env, tùy chỉnh khung giờ gửi linh hoạt và điều khiển chạy bot trực tiếp.
"""

import os
import sys
import json
import time
import re
import socket
import webbrowser
import threading
import subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 7860
ENV_FILE = os.path.abspath(".env")
WORKFLOW_FILE = os.path.abspath(os.path.join(".github", "workflows", "schedule.yml"))
LOG_FILE = os.path.abspath(os.path.join("logs", "app.log"))

RUNNER_STATE = {
    "status": "idle",
    "logs": [],
    "process": None,
    "last_exit_code": None,
    "started_at": None,
}

SAMPLE_MESSAGES = {
    "vi": [
        "🔥 Duy trì chuỗi TikTok hôm nay nè! Chúc bạn ngày mới tốt lành ✨",
        "🔥 Tiếp tục chuỗi hỏa hoạn TikTok nha! Ngày mới tràn đầy năng lượng nhé 💪",
        "🔥 Rep chuỗi TikTok hôm nay nào! Chúc bạn một ngày thật may mắn 🍀",
        "🔥 Giữ chuỗi TikTok thôi nào! Have a wonderful day 🌟",
        "🔥 Ting ting! Điểm danh chuỗi TikTok ngày hôm nay 🚀",
        "🔥 Giữ lửa TikTok không để tắt nè bạn ơi! Chúc ngày mới vui vẻ 🎉",
        "🔥 Chuỗi TikTok hôm nay nè! Chúc bạn mọi điều suôn sẻ nha ❤️",
        "🔥 Rep chuỗi giữ lửa nè! Ngày mới an lành và nhiều niềm vui nhé 🌈",
    ],
    "en": [
        "🔥 Keeping our TikTok streak alive! Have an amazing day ✨",
        "🔥 Streak check! Hope you have a wonderful day ahead 🚀",
        "🔥 Daily TikTok streak reminder! Stay awesome and blessed 🍀",
        "🔥 Keeping the fire burning on TikTok! Have a great one 🎉",
        "🔥 Don't let our streak end! Wishing you the best today 💖",
        "🔥 Here is our daily streak! Wishing you good vibes and positivity 🌟",
        "🔥 Replying for our streak! Have a super productive day 💪",
    ],
    "bilingual": [
        "🔥 Giữ chuỗi TikTok hôm nay nha! • Keeping our streak alive ✨",
        "🔥 Điểm danh chuỗi TikTok nè! • Have a wonderful day 🌟",
        "🔥 Rep chuỗi giữ lửa TikTok! • Wishing you all the best today 🍀",
        "🔥 Tiếp tục chuỗi ngày rực rỡ nhé! • Stay awesome and blessed 💖",
        "🔥 Giữ lửa TikTok không để tắt nè! • Daily streak reminder 🎉",
    ],
}


def read_env_raw():
    if not os.path.exists(ENV_FILE):
        return {}
    res = {}
    with open(ENV_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
                    v = v[1:-1]
                res[k] = v
    return res


def update_env_file(updates: dict):
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

    keys_updated = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                val = updates[k]
                new_lines.append(f"{k}={val}\n")
                keys_updated.add(k)
                continue
        new_lines.append(line)

    for k, val in updates.items():
        if k not in keys_updated:
            new_lines.append(f"{k}={val}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Đồng bộ song song sang config.json
    try:
        cfg_path = os.path.abspath("config.json")
        cfg_data = {}
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as cf:
                cfg_data = json.load(cf)
        if "TASKS" in updates:
            try:
                t_list = json.loads(updates["TASKS"])
                if t_list and isinstance(t_list, list):
                    cfg_data["account"] = t_list[0]
            except Exception:
                pass
        if "STREAK_LANGUAGE" in updates:
            cfg_data["streak_language"] = updates["STREAK_LANGUAGE"]
        if "MESSAGE_TEMPLATE" in updates:
            cfg_data["message_template"] = updates["MESSAGE_TEMPLATE"]
        if "SCHEDULE_TIMES" in updates:
            cfg_data["schedule_times"] = [x.strip() for x in updates["SCHEDULE_TIMES"].split(",") if x.strip()]
        if "RANDOM_DELAY_MINUTES" in updates:
            try:
                cfg_data["random_delay_minutes"] = int(updates["RANDOM_DELAY_MINUTES"])
            except Exception:
                pass
        cfg_data["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(cfg_path, "w", encoding="utf-8") as cf:
            json.dump(cfg_data, cf, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"Lỗi đồng bộ config.json: {ex}")

    # Tự động đẩy lên GitHub ngầm trong nền (background thread) để không cần nhập key
    threading.Thread(target=auto_git_push_to_github, daemon=True).start()


def auto_git_push_to_github():
    """
    Tự động commit và đẩy config.json và workflow lên GitHub
    bằng Git Credential sẵn có trên máy mà không cần người dùng nhập key.
    """
    try:
        subprocess.run(["git", "add", "config.json", ".github/workflows/schedule.yml"], capture_output=True, text=True, timeout=15)
        diff_res = subprocess.run(["git", "diff", "--cached", "--quiet"], timeout=10)
        if diff_res.returncode != 0:
            subprocess.run(["git", "commit", "-m", "Cập nhật cấu hình & lịch trình từ Web Dashboard"], capture_output=True, text=True, timeout=15)
            push_res = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, timeout=30)
            if push_res.returncode == 0:
                print("☁️ [ĐỒNG BỘ GITHUB] Đã tự động đẩy cấu hình mới lên GitHub thành công!")
    except Exception as e:
        print(f"Lỗi tự động đẩy GitHub: {e}")



def update_github_workflow_schedule(times_vn: list):
    """
    Tự động chuyển đổi các khung giờ Việt Nam (UTC+7) sang giờ UTC
    và ghi đè trực tiếp vào file .github/workflows/schedule.yml
    """
    if not os.path.exists(WORKFLOW_FILE):
        return False, "Không tìm thấy file .github/workflows/schedule.yml"

    cron_entries = []
    for t in times_vn:
        t = str(t).strip()
        if not t:
            continue
        try:
            parts = t.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            # Giờ VN là UTC+7 -> Trừ 7 tiếng ra UTC
            total_mins = (h * 60 + m - 7 * 60) % (24 * 60)
            utc_h = total_mins // 60
            utc_m = total_mins % 60
            cron_entries.append(f'    - cron: "{utc_m} {utc_h} * * *"  # {h:02d}:{m:02d} VN (UTC+7)')
        except Exception:
            continue

    if not cron_entries:
        cron_entries = ['    - cron: "0 1,13 * * *"  # Mặc định 08:00, 20:00 VN']

    cron_block = "\n".join(cron_entries)

    with open(WORKFLOW_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r'(  schedule:\n)(?:    #.*\n)*(?:    - cron:[^\n]*\n*)+'
    if re.search(pattern, content):
        new_content = re.sub(pattern, f'  schedule:\n{cron_block}\n', content, count=1)
    else:
        new_content = re.sub(r'  schedule:[\s\S]*?(?=jobs:)', f'  schedule:\n{cron_block}\n\n', content)

    with open(WORKFLOW_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True, cron_entries


def get_full_config():
    env_vars = read_env_raw()
    raw_tasks = env_vars.get("TASKS", "[]")
    try:
        tasks = json.loads(raw_tasks)
    except Exception:
        tasks = []

    raw_cookies = env_vars.get("COOKIES_ACC1", "[]")
    cookie_count = 0
    try:
        cookies = json.loads(raw_cookies)
        if isinstance(cookies, list):
            cookie_count = len(cookies)
    except Exception:
        cookies = []

    streak_lang = env_vars.get("STREAK_LANGUAGE", "vi")
    message_tmpl = env_vars.get("MESSAGE_TEMPLATE", "[RANDOM_MESSAGE]")

    # Khung giờ gửi tin
    sched_str = env_vars.get("SCHEDULE_TIMES", "08:30,20:30")
    schedule_times = [t.strip() for t in sched_str.split(",") if t.strip()]
    try:
        random_delay = int(env_vars.get("RANDOM_DELAY_MINUTES", "10"))
    except ValueError:
        random_delay = 10

    acc_targets = []
    account_name = "Tài khoản của tôi"
    unique_id = "acc1"

    if tasks and isinstance(tasks, list):
        first_acc = tasks[0]
        account_name = first_acc.get("username", account_name)
        unique_id = first_acc.get("unique_id", unique_id)
        acc_targets = first_acc.get("targets", [])

    return {
        "status": "success",
        "env_path": ENV_FILE,
        "exists": os.path.exists(ENV_FILE),
        "account": {
            "username": account_name,
            "unique_id": unique_id,
            "targets": acc_targets,
            "cookie_count": cookie_count,
            "has_session": cookie_count > 0,
        },
        "streak_language": streak_lang,
        "message_template": message_tmpl,
        "schedule_times": schedule_times,
        "random_delay_minutes": random_delay,
        "tasks_json": json.dumps(tasks, ensure_ascii=False),
        "cookies_json": raw_cookies,
    }


def add_target_name(target_name: str):
    target_name = target_name.strip()
    if not target_name:
        return False, "Tên mục tiêu không được để trống"

    env_vars = read_env_raw()
    try:
        tasks = json.loads(env_vars.get("TASKS", "[]"))
    except Exception:
        tasks = []

    if not tasks:
        tasks = [{"username": "Tài khoản của tôi", "unique_id": "acc1", "targets": []}]

    current_targets = tasks[0].get("targets", [])
    if target_name in current_targets:
        return False, f"Mục tiêu '{target_name}' đã có trong danh sách"

    current_targets.append(target_name)
    tasks[0]["targets"] = current_targets

    update_env_file({"TASKS": json.dumps(tasks, ensure_ascii=False)})
    return True, current_targets


def delete_target_name(target_name: str):
    target_name = target_name.strip()
    env_vars = read_env_raw()
    try:
        tasks = json.loads(env_vars.get("TASKS", "[]"))
    except Exception:
        tasks = []

    if not tasks:
        return False, "Không tìm thấy cấu hình tài khoản"

    current_targets = tasks[0].get("targets", [])
    if target_name not in current_targets:
        return False, f"Không tìm thấy mục tiêu '{target_name}'"

    current_targets = [t for t in current_targets if t != target_name]
    tasks[0]["targets"] = current_targets

    update_env_file({"TASKS": json.dumps(tasks, ensure_ascii=False)})
    return True, current_targets


def run_bot_subprocess():
    global RUNNER_STATE
    RUNNER_STATE["status"] = "running"
    RUNNER_STATE["logs"] = []
    RUNNER_STATE["started_at"] = time.strftime("%H:%M:%S")

    def worker():
        try:
            cmd = [sys.executable, "-u", "main.py"]
            RUNNER_STATE["logs"].append(f"[{time.strftime('%H:%M:%S')}] 🚀 Bắt đầu chạy: {' '.join(cmd)}")
            
            # Chạy thử thủ công thì bỏ qua delay ngẫu nhiên để phản hồi nhanh
            env = os.environ.copy()
            env["SKIP_RANDOM_DELAY"] = "true"

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            RUNNER_STATE["process"] = proc

            for line in proc.stdout:
                line_str = line.strip()
                if line_str:
                    RUNNER_STATE["logs"].append(f"[{time.strftime('%H:%M:%S')}] {line_str}")
                    if len(RUNNER_STATE["logs"]) > 200:
                        RUNNER_STATE["logs"].pop(0)

            proc.wait()
            RUNNER_STATE["last_exit_code"] = proc.returncode
            if proc.returncode == 0:
                RUNNER_STATE["status"] = "completed"
                RUNNER_STATE["logs"].append(f"[{time.strftime('%H:%M:%S')}] ✅ Đã hoàn tất rep chuỗi thành công!")
            else:
                RUNNER_STATE["status"] = "error"
                RUNNER_STATE["logs"].append(f"[{time.strftime('%H:%M:%S')}] ❌ Tiến trình kết thúc với mã lỗi {proc.returncode}")
        except Exception as e:
            RUNNER_STATE["status"] = "error"
            RUNNER_STATE["logs"].append(f"[{time.strftime('%H:%M:%S')}] ❌ Lỗi: {e}")
        finally:
            RUNNER_STATE["process"] = None

    t = threading.Thread(target=worker, daemon=True)
    t.start()


def schedule_watcher():
    """Kiểm tra thời gian và kích hoạt rep chuỗi nếu đến giờ đã đặt khi tool đang mở trên máy"""
    last_triggered_minute = ""
    while True:
        try:
            time.sleep(20)
            now = time.localtime()
            current_time = f"{now.tm_hour:02d}:{now.tm_min:02d}"
            
            if current_time == last_triggered_minute:
                continue

            env_vars = read_env_raw()
            sched_str = env_vars.get("SCHEDULE_TIMES", "")
            if not sched_str:
                continue
            
            sched_times = [t.strip() for t in sched_str.split(",") if t.strip()]
            if current_time in sched_times:
                last_triggered_minute = current_time
                print(f"\n⏰ [TỰ ĐỘNG ĐẾN GIỜ] {current_time} - Kích hoạt tiến trình rep chuỗi...")
                if RUNNER_STATE["status"] != "running":
                    run_bot_subprocess()
        except Exception:
            pass


class ManagerHTTPHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open("Quan_Ly_TikTok_Streak.html", "rb") as f:
                self.wfile.write(f.read())
            return

        if path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            data = get_full_config()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/sample-messages":
            params = parse_qs(parsed.query)
            lang = params.get("lang", ["vi"])[0]
            messages = SAMPLE_MESSAGES.get(lang, SAMPLE_MESSAGES["vi"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"lang": lang, "messages": messages}, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/run-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "status": RUNNER_STATE["status"],
                        "logs": RUNNER_STATE["logs"][-60:],
                        "started_at": RUNNER_STATE["started_at"],
                        "last_exit_code": RUNNER_STATE["last_exit_code"],
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return

        if path == "/api/logs":
            lines = []
            if os.path.exists(LOG_FILE):
                try:
                    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                        lines = [l.strip() for l in f.readlines()[-60:] if l.strip()]
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"logs": lines}, ensure_ascii=False).encode("utf-8"))
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"

        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/target/add":
            target = payload.get("target", "")
            ok, msg_or_list = add_target_name(target)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "success": ok,
                        "message": "Đã thêm thành công" if ok else msg_or_list,
                        "targets": msg_or_list if ok else [],
                        "config": get_full_config(),
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return

        if path == "/api/target/delete":
            target = payload.get("target", "")
            ok, msg_or_list = delete_target_name(target)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "success": ok,
                        "message": "Đã xóa thành công" if ok else msg_or_list,
                        "targets": msg_or_list if ok else [],
                        "config": get_full_config(),
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            return

        if path == "/api/language":
            lang = payload.get("language", "vi")
            update_env_file({"STREAK_LANGUAGE": lang})
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"success": True, "language": lang, "config": get_full_config()}, ensure_ascii=False
                ).encode("utf-8")
            )
            return

        if path == "/api/template":
            tmpl = payload.get("template", "[RANDOM_MESSAGE]")
            update_env_file({"MESSAGE_TEMPLATE": tmpl})
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"success": True, "template": tmpl, "config": get_full_config()}, ensure_ascii=False).encode(
                    "utf-8"
                )
            )
            return

        if path == "/api/schedule":
            times = payload.get("times", ["08:30", "20:30"])
            delay = payload.get("random_delay_minutes", 10)
            if isinstance(times, list):
                # Lưu vào .env
                update_env_file({
                    "SCHEDULE_TIMES": ",".join(times),
                    "RANDOM_DELAY_MINUTES": str(delay),
                })
                # Cập nhật trực tiếp vào file .github/workflows/schedule.yml
                ok, crons = update_github_workflow_schedule(times)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "success": True,
                            "times": times,
                            "random_delay_minutes": delay,
                            "crons": crons if ok else [],
                            "config": get_full_config(),
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return

        if path == "/api/save-all":
            updates = {}
            if "streak_language" in payload:
                updates["STREAK_LANGUAGE"] = payload["streak_language"]
            if "message_template" in payload:
                updates["MESSAGE_TEMPLATE"] = payload["message_template"]
            if "schedule_times" in payload and isinstance(payload["schedule_times"], list):
                updates["SCHEDULE_TIMES"] = ",".join(payload["schedule_times"])
                update_github_workflow_schedule(payload["schedule_times"])
            if "random_delay_minutes" in payload:
                updates["RANDOM_DELAY_MINUTES"] = str(payload["random_delay_minutes"])
            if "targets" in payload and isinstance(payload["targets"], list):
                env_vars = read_env_raw()
                try:
                    tasks = json.loads(env_vars.get("TASKS", "[]"))
                except Exception:
                    tasks = []
                if not tasks:
                    tasks = [{"username": "Tài khoản của tôi", "unique_id": "acc1", "targets": []}]
                tasks[0]["targets"] = payload["targets"]
                updates["TASKS"] = json.dumps(tasks, ensure_ascii=False)

            if updates:
                update_env_file(updates)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"success": True, "config": get_full_config()}, ensure_ascii=False).encode("utf-8")
            )
            return

        if path == "/api/run":
            if RUNNER_STATE["status"] == "running":
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"success": False, "message": "Bot đang chạy, vui lòng chờ..."}, ensure_ascii=False).encode(
                        "utf-8"
                    )
                )
                return

            run_bot_subprocess()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"success": True, "message": "Đã bắt đầu chạy bot!"}, ensure_ascii=False).encode("utf-8")
            )
            return

        if path == "/api/login-browser":
            try:
                subprocess.Popen(["cmd.exe", "/c", "start", "cmd.exe", "/k", sys.executable, "login_helper.py"])
                msg = "Đã mở cửa sổ đăng nhập Chrome TikTok!"
                ok = True
            except Exception as e:
                msg = f"Lỗi khởi động đăng nhập: {e}"
                ok = False

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok, "message": msg}, ensure_ascii=False).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    global PORT
    while is_port_in_use(PORT):
        PORT += 1

    server_address = ("127.0.0.1", PORT)
    httpd = ThreadingHTTPServer(server_address, ManagerHTTPHandler)
    url = f"http://127.0.0.1:{PORT}"

    print("=" * 65)
    print("🔥 TRÌNH QUẢN LÝ TIKTOK STREAK SAVER ĐANG CHẠY 🔥")
    print(f"👉 Địa chỉ Web App: {url}")
    print(f"📂 File cấu hình kết nối: {ENV_FILE}")
    print("=" * 65)
    print("Mọi thao tác trên web sẽ ĐỒNG BỘ TRỰC TIẾP vào file .env!")
    print("Nhấn Ctrl + C để dừng máy chủ.")
    print("-" * 65)

    # Chạy thread theo dõi lịch gửi định kỳ khi mở máy
    threading.Thread(target=schedule_watcher, daemon=True).start()

    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Đang dừng máy chủ quản lý...")
        httpd.shutdown()
        print("✅ Đã dừng.")


if __name__ == "__main__":
    main()

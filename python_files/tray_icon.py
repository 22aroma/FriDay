import os
import sys
import subprocess
import threading
import pystray
from PIL import Image

from python_files.constants import ICON_PATH, LOG_PATH
from python_files.logger import log_message
from python_files.commands import shutdown_event


def load_tray_icon():
    """Загружаем иконку для трея."""
    try:
        img = Image.open(ICON_PATH)
        img.load()
        copy = img.copy()
        img.close()
        return copy
    except Exception as e:
        log_message(f"Ошибка загрузки иконки: {e}", "tray_icon.py")
        return None


def _on_quit(icon, item):
    shutdown_event.set()
    icon.stop()


def _on_restart(icon, item):
    env = os.environ.copy()
    env["FRIDAY_RESTART"] = "1"
    subprocess.Popen([sys.executable] + sys.argv, env=env)
    _on_quit(icon, item)


def _on_open_logs(icon, item):
    os.startfile(LOG_PATH)


def run_tray_icon():
    """Запускаем иконку в трее с автоматическим перезапуском при ошибках."""
    while not shutdown_event.is_set():
        try:
            image = load_tray_icon()
            if image is None:
                return

            menu = pystray.Menu(
                pystray.MenuItem("Логи", _on_open_logs),
                pystray.MenuItem("Перезапуск", _on_restart),
                pystray.MenuItem("Выйти", _on_quit),
            )

            icon = pystray.Icon(name="FriDay", icon=image, title="FriDay", menu=menu)
            icon.run()
        except Exception as e:
            log_message(f"Ошибка в трее: {e}", "tray_icon.py")

        if not shutdown_event.is_set():
            log_message("Иконка трея перезапускается...", "tray_icon.py")


def start_hotbar():
    tray_thread = threading.Thread(target=run_tray_icon, name="TrayIconThread")
    tray_thread.daemon = True
    tray_thread.start()
    return tray_thread

import threading
import pystray
from PIL import Image

from python_files.constants import ICON_PATH
from python_files.logger import log_message

# Глобальные переменные
shutdown_event = None

def init_hotbar(event, pid=None):
    global shutdown_event
    shutdown_event = event


def load_tray_icon():
    try:
        image = Image.open(ICON_PATH)
        log_message(f"Иконка загружена: {ICON_PATH}", "tray_icon.py")
        return image
    except Exception as e:
        log_message(f"Ошибка загрузки иконки: {e}", "tray_icon.py")
        return None

def run_tray_icon():
    try:
        image = load_tray_icon()
        
        icon = pystray.Icon(
            name="FriDay",
            icon=image,
            title="FriDay"
        )
        
        log_message("Иконка создана", "tray_icon.py")
        icon.run()
        
    except Exception as e:
        log_message(f"Ошибка в иконке трея: {e}", "tray_icon.py")

def start_hotbar():
    tray_thread = threading.Thread(target=run_tray_icon, name="TrayIconThread")
    tray_thread.daemon = True
    tray_thread.start()
    return tray_thread

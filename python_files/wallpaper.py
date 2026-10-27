import os
import random
import subprocess
import sys

from python_files.logger import log_message

# Скрипт использует .NET COM-интероп (Add-Type). Чистый ctypes для этого
# COM-объекта не подходит: на активацию CLSID_ImmersiveShell отвечает только
# штатный путь .NET (Activator.CreateInstance), CoCreateInstance возвращает
# в ряде систем 0x80040154. На диск ничего не пишется.
_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wallpaper.ps1")
_SUPPORTED_MIN = 22621  # Windows 11 22H2 — первая с обоями на рабочих столах
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff")


def _pick_image(path):
    """Возвращает (файл, ошибка): файл из папки (случайно) или сам файл."""
    if os.path.isdir(path):
        try:
            files = sorted(
                f for f in os.listdir(path)
                if f.lower().endswith(_IMAGE_EXTS)
            )
        except OSError as e:
            log_message(f"Не удалось прочитать папку обоев: {e}", "wallpaper.py")
            return None, "Не удалось прочитать папку с обоями"
        if not files:
            log_message(f"В папке нет картинок: {path}", "wallpaper.py")
            return None, "В папке нет картинок"
        chosen = random.choice(files)
        log_message(f"Выбрана случайная картинка: {chosen}", "wallpaper.py")
        return os.path.join(path, chosen), None
    if os.path.isfile(path):
        return path, None
    return None, "Папка с обоями не найдена"


def set_all_desktop_wallpapers(path):
    """Меняет обои сразу на всех виртуальных рабочих столах Windows 11.

    path — путь к файлу или к папке (из папки выбирается случайная картинка).
    Возвращает None при успехе или строку с описанием ошибки.
    """
    log_message(f"Смена обоев: {path}", "wallpaper.py")

    if not path:
        log_message("Путь к обоям не задан", "wallpaper.py")
        return "Не указана папка с обоями"

    filepath, err = _pick_image(path)
    if err:
        return err

    build = sys.getwindowsversion().build
    if build < _SUPPORTED_MIN:
        log_message(f"Не поддерживаемая версия Windows (build {build})", "wallpaper.py")
        return "Версия системы не поддерживается"
    if not os.path.isfile(_SCRIPT):
        log_message(f"Не найден скрипт: {_SCRIPT}", "wallpaper.py")
        return "Не найден скрипт смены обоев"

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", _SCRIPT, "-Path", filepath],
            capture_output=True, text=True, timeout=60,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        log_message(f"Ошибка запуска powershell: {e}", "wallpaper.py")
        return "Не удалось запустить скрипт"

    if result.returncode != 0:
        err = (result.stdout + result.stderr).strip()
        if err:
            log_message(f"powershell вернул {result.returncode}: {err}", "wallpaper.py")
            return err[-200:]
        log_message(f"powershell вернул код {result.returncode}", "wallpaper.py")
        return "Возникла ошибка скрипта"

    log_message(f"Обои сменены на всех рабочих столах: {filepath}", "wallpaper.py")
    return None
import sys
import os
import time
import signal
import traceback

# Добавляем корневую папку в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── ЕДИНСТВЕННЫЙ ЭКЗЕМПЛЯР ──────────────────────────────────────────────────
# Не даём запуститься второй копии (повторный клик «Запустить» и т.п.):
# приложение молча завершается, если уже работает. Мутекс автоматически
# освобождается системой при завершении процесса.
import ctypes
import ctypes.wintypes as _wintypes

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = _wintypes.HANDLE
_Mutex = _kernel32.CreateMutexW(None, False, "Local\\FriDayAssistant")
if ctypes.get_last_error() == 183:
    _kernel32.CloseHandle(_Mutex)
    _Mutex = None
    if os.environ.get("FRIDAY_RESTART") == "1":
        _kernel32.OpenMutexW.restype = _wintypes.HANDLE
        _kernel32.OpenMutexW.argtypes = [_wintypes.DWORD, _wintypes.BOOL, _wintypes.LPCWSTR]
        _SYNCHRONIZE = 0x00100000
        for _ in range(200):
            time.sleep(0.1)
            h = _kernel32.OpenMutexW(_SYNCHRONIZE, False, "Local\\FriDayAssistant")
            if not h:
                break
            _kernel32.CloseHandle(h)
        else:
            sys.exit(0)
        _Mutex = _kernel32.CreateMutexW(None, False, "Local\\FriDayAssistant")
        if ctypes.get_last_error() == 183:
            sys.exit(0)
    else:
        sys.exit(0)

# Отключаем интерактивность torch
os.environ['TORCH_HUB_NO_INTERACTION'] = '1'
# Ограничиваем потоки OpenMP ДО импорта torch: иначе OpenMP резервирует
# огромные арены ~550 МБ commit (та самая кажущаяся "зоопарк" при запуске ~1 ГБ).
# ASR/onnxruntime не затрагивается: transcribe.cpp работает отдельным
# нативным процессом (ggml), onnxruntime сам задаёт число потоков.
os.environ['OMP_NUM_THREADS'] = '1'
import torch
torch.set_num_threads(1)

# Если нет консоли (pyw) — перенаправляем вывод
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# ─── ИМПОРТЫ МОДУЛЕЙ ─────────────────────────────────────────────────────────

from python_files.constants import FILES_DIR, LOG_PATH
from python_files.config_loader import cfg
from python_files.logger import log_message, close_log
from python_files import settings
from python_files.tts import speak
from python_files.tray_icon import start_hotbar
from python_files import commands
from python_files.commands import init_memory_buffer
from python_files.audio_mixer import _mixer
from python_files.settings import safe_read

# ─── GC ───────────────────────────────────────────────────────────────────────
# Замораживаем всё, что импортировано при старте: это огромный граф объектов
# (torch и прочие библиотеки). Без заморозки сборщик мусора периодически
# сканирует его целиком → короткие, но заметные спайки CPU.
import gc
gc.freeze()

os.makedirs(FILES_DIR, exist_ok=True)
open(LOG_PATH, 'w').close()


# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────────────────────

def write_crash_log(source, message):
    """Записываем traceback в лог."""
    buf = traceback.format_exc()
    for line in buf.splitlines():
        log_message(line, source)
    log_message(f"[TRACEBACK_END] {message}", source)


def check_alarms_and_timers():
    """Проверяем, не сработали ли будильник или таймер."""
    now = time.time()
    if commands.alarm_time and now >= commands.alarm_time:
        commands.alarm_time = None
        speak("Будильник сработал")
    if commands.timer_end_time and now >= commands.timer_end_time:
        commands.timer_end_time = None
        speak("Таймер сработал")


def normalize_query(text, wake_word):
    """Убираем ключевое слово и исправляем распространённые ошибки распознавания."""
    q = text.lower().replace(wake_word, "").strip()
    return q


def cleanup_all():
    """Полная очистка при выходе."""
    commands.shutdown_event.set()
    try:
        if 'stream' in globals() and stream is not None:
            stream.stop()
            stream.close()
    except Exception as e:
        log_message(f"Ошибка при очистке аудио: {e}", "FriDay.pyw")
    _mixer.close()
    settings.cleanup()
    close_log()


def _signal_handler(sig, frame):
    log_message(f"Получен сигнал {sig}, завершение", "FriDay.pyw")
    cleanup_all()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
if hasattr(signal, 'SIGTERM'):
    signal.signal(signal.SIGTERM, _signal_handler)


# ─── ИНИЦИАЛИЗАЦИЯ ───────────────────────────────────────────────────────────

log_message(
    f"Стартовал | TTS: speaker={cfg.tts.speaker}, model={cfg.tts.model_id} | wake_word={cfg.wake_word}",
    "FriDay.pyw",
)

try:
    audio_settings = settings.get_settings()
    CHUNK = audio_settings["chunk"]
    listener = audio_settings["listener"]
    stream = audio_settings["stream"]
except Exception:
    write_crash_log(__file__, "get_settings error")
    log_message("Ошибка инициализации аудио", "FriDay.pyw")
    sys.exit(1)

init_memory_buffer(ttl=cfg.memory_ttl)
listening_mode_active = False


# ─── РЕЖИМ ПРОСЛУШИВАНИЯ КОМАНД (ПОСЛЕ АКТИВАЦИИ) ───────────────────────────

def activate_listening_mode():
    """Слушаем команды в течение listening_duration секунд после активации."""
    global listening_mode_active

    if listening_mode_active:
        return

    listening_mode_active = True
    _mixer.music_volume = 0.15

    try:
        listener.reset()
        speak("Слушаю вас")

        start_time = time.time()
        duration = cfg.listening_duration

        while not commands.shutdown_event.is_set() and time.time() - start_time < duration:
            check_alarms_and_timers()

            try:
                data, _ = safe_read(stream, CHUNK)
                audio_np = data.flatten()
                finalized, text = listener.process_chunk(audio_np)

                if finalized and text:
                    # Обновляем буфер памяти
                    if commands.memory_buffer:
                        commands.memory_buffer.update(text)

                    query = normalize_query(text, cfg.wake_word)
                    if query:
                        result = commands.command_handler(query)
                        if result is not None:
                            # Ждём окончания TTS и сбрасываем таймер
                            while _mixer.tts_playing:
                                time.sleep(0.05)
                            start_time = time.time()
                        listener.reset()

            except Exception:
                log_message("Ошибка чтения в режиме команд", "FriDay.pyw")
                write_crash_log("FriDay.pyw", "Ошибка чтения в режиме команд")
                time.sleep(0.05)
    finally:
        listening_mode_active = False
        _mixer.music_volume = 1.0


# ─── ОСНОВНОЙ ЦИКЛ: ОБНАРУЖЕНИЕ КЛЮЧЕВОГО СЛОВА ─────────────────────────────

def run_wake_word_detection():
    """Главный цикл: слушаем микрофон и ищем ключевое слово "Пятница".

    Три режима:
      1. "Пятница, погода?" — сразу выполняем команду из той же фразы
      2. "Пятница" — активируем режим прослушивания команд
      3. "Погода?" (без ключевого слова) — запоминаем на 120 сек.
         Если потом скажут "Пятница" — выполним запомненную команду.
    """
    global listening_mode_active

    log_message("Запуск обнаружения ключевого слова", "FriDay.pyw")
    wake_word = cfg.wake_word
    last_detection_time = 0
    cooldown = cfg.detection_cooldown
    last_diag_time = time.time()

    try:
        while not commands.shutdown_event.is_set():
            current_time = time.time()
            check_alarms_and_timers()

            # Диагностика каждые 5 минут
            if current_time - last_diag_time > 300:
                last_diag_time = current_time
                log_message(
                    f"Жив: in_speech={listener.in_speech}, "
                    f"buffer={len(listener.speech_buffer)}, "
                    f"listening_mode={listening_mode_active}",
                    "FriDay.pyw",
                )

            # Если активен режим команд — просто ждём
            if listening_mode_active:
                time.sleep(0.05)
                continue

            try:
                data, _ = safe_read(stream, CHUNK)
                audio_np = data.flatten()
                finalized, text = listener.process_chunk(audio_np)

                if not finalized or not text:
                    continue

                text_lower = text.lower()

                # ── КЛЮЧЕВОЕ СЛОВО НАЙДЕНО ────────────────────────────────
                if wake_word in text_lower:
                    if current_time - last_detection_time <= cooldown:
                        continue
                    last_detection_time = current_time
                    listener.reset()

                    # Режим 3: есть отложенный вопрос — выполняем его
                    if commands.memory_buffer:
                        deferred = commands.memory_buffer.get_deferred()
                        if deferred:
                            log_message(f"Режим 3 (Отложенный): '{deferred}'", "FriDay.pyw")
                            commands.memory_buffer.clear()
                            result = commands.command_handler(deferred)
                            listener.reset()
                            if result is None:
                                log_message("Режим 3: не распознано → режим 2", "FriDay.pyw")
                                activate_listening_mode()
                            continue

                    # Режим 1: ключевое слово + команда в одной фразе
                    command_part = text_lower.replace(wake_word, "").strip(".,!?:; ")
                    if command_part:
                        log_message(f"Режим 1 (Мгновенный): '{command_part}'", "FriDay.pyw")
                        if commands.memory_buffer:
                            commands.memory_buffer.clear()
                        query = normalize_query(command_part, wake_word)
                        result = commands.command_handler(query)
                        listener.reset()
                        if result is None:
                            log_message("Режим 1: не распознано → режим 2", "FriDay.pyw")
                            activate_listening_mode()
                        continue

                    # Режим 2: только ключевое слово → слушаем команду
                    log_message("Режим 2 (Ожидание): переход в режим команд", "FriDay.pyw")
                    if commands.memory_buffer:
                        commands.memory_buffer.clear()
                    activate_listening_mode()
                    listener.reset()

                # ── КЛЮЧЕВОГО СЛОВА НЕТ ───────────────────────────────────
                else:
                    # Запоминаем фразу для режима 3
                    if commands.memory_buffer:
                        commands.memory_buffer.update(text_lower)
                        commands.memory_buffer.mark_deferred()

            except Exception:
                log_message("Ошибка при чтении аудио", "FriDay.pyw")
                traceback.print_exc()
                time.sleep(0.05)
                continue

    except Exception:
        log_message("Исключение в основном цикле", "FriDay.pyw")
        traceback.print_exc()
    finally:
        cleanup_all()


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

def start():
    log_message("Запуск иконки в трее...", "FriDay.pyw")
    hotbar_thread = start_hotbar()
    if hotbar_thread:
        log_message(f"Иконка запущена: {hotbar_thread.name}", "FriDay.pyw")
    else:
        log_message("Не удалось запустить иконку", "FriDay.pyw")

    log_message("Запуск основного цикла", "FriDay.pyw")
    run_wake_word_detection()


if __name__ == "__main__":
    start()

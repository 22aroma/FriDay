import sys
import os
import time
import numpy as np
import signal

from python_files.constants import BASE_DIR, LOG_PATH
from python_files.logger import log_message
from python_files import settings
from python_files.FriDay_say import FriDay_say_, cleanup_pyaudio
from python_files.tts import speak
from python_files.tray_icon import init_hotbar, start_hotbar
from python_files import commands
from python_files.commands import MemoryBuffer, init_memory_buffer

open(LOG_PATH, 'w').close()

def cleanup_all():
    """Полная очистка при выходе"""
    global stream, p
    try:
        if 'stream' in globals() and stream and stream.is_active():
            stream.stop_stream()
            stream.close()
        if 'p' in globals() and p:
            p.terminate()
    except Exception as e:
        log_message(f"Ошибка при очистке аудио: {e}", "FriDay.pyw")
    
    cleanup_pyaudio()

def cleanup_audio():
    cleanup_all()

def _signal_handler(sig, frame):
    log_message(f"Получен сигнал {sig}, завершение", "FriDay.py")
    cleanup_all()
    os._exit(0)

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


log_message("Стартовал с PyAudio", "FriDay.py")


try:
    from python_files.stt import preload_models
    log_message("Предзагрузка моделей распознавания...", "FriDay.py")
    preload_models()
    log_message("Модели загружены", "FriDay.py")
except Exception as e:
    log_message(f"Ошибка предзагрузки: {e}", "FriDay.py")

try:
    CHUNK, sample_rate, listener, p, stream = settings.get_settings()
except Exception as e:
    log_message(f"Ошибка: {e}", "FriDay.py")
    sys.exit(1)

init_memory_buffer(ttl=120)
listening_mode_active = False


def _activate_listening_mode():
    """Активирует режим прослушивания команд на 15 секунд"""
    global listening_mode_active
    
    if listening_mode_active:
        return
    
    listening_mode_active = True
    
    try:
        listener.reset()
        
        path = os.path.join(BASE_DIR, "FriDay_say", "wwd", "listen.wav")
        FriDay_say_(path)
        
        start_time = time.time()
        listening_duration = 15
        while not commands.shutdown_event.is_set() and time.time() - start_time < listening_duration:
            current_time = time.time()
            
            if commands.alarm_time and current_time >= commands.alarm_time:
                commands.alarm_time = None
                speak("Будильник сработал")
            
            if commands.timer_end_time and current_time >= commands.timer_end_time:
                commands.timer_end_time = None
                speak("Таймер сработал")
            
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16)
                
                finalized, text = listener.process_chunk(audio_np)
                
                if finalized and text:
                    if commands.memory_buffer:
                        commands.memory_buffer.update(text)
                    query = text.replace("пятница", "").replace("пятницу", "").strip()
                    if query:
                        query = (query
                            .replace("пятницу", "пятница")
                            .replace("завершил работу", "заверши работу")
                            .replace("перезагрузить компьютер", "перезагрузи компьютер"))
                        commands.command_handler(query)
                        start_time = time.time()
                        listener.reset()
                    
            except Exception as e:
                log_message(f"Ошибка чтения в режиме команд: {e}", "FriDay.py")
                time.sleep(0.05)
    finally:
        listening_mode_active = False


def WWD():
    """Wake Word Detection loop с Silero VAD + Kairos ASR

    3 режима активации:
      Mode 1 (Мгновенный): "Пятница, погода?" → сразу ответ
      Mode 2 (Ожидание):   "Пятница" → звук → команда → ответ
      Mode 3 (Отложенный): "Погода?" (без wake-word) → буфер 120с → "Пятница" → ответ
    """
    global listening_mode_active
    
    log_message("WWD: старт функции обнаружения ключевого слова (VAD + KairosASR)", "FriDay.py")
    wake_word = "пятница"
    last_detection_time = 0
    detection_cooldown = 2
    
    try:
        while not commands.shutdown_event.is_set():
            current_time = time.time()
            
            if commands.alarm_time and current_time >= commands.alarm_time:
                commands.alarm_time = None
                speak("Будильник сработал")
            
            if commands.timer_end_time and current_time >= commands.timer_end_time:
                commands.timer_end_time = None
                speak("Таймер сработал")
            
            if listening_mode_active:
                time.sleep(0.05)
                continue
            
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16)
                
                finalized, text = listener.process_chunk(audio_np)
                
                if finalized and text:
                    if wake_word in text:
                        if current_time - last_detection_time > detection_cooldown:
                            last_detection_time = current_time
                            listener.reset()
                            
                            # Mode 3: отложенный вопрос из буфера
                            if commands.memory_buffer:
                                deferred = commands.memory_buffer.get_deferred()
                                if deferred:
                                    log_message(f"Mode 3 (Отложенный): '{deferred}'", "FriDay.py")
                                    commands.memory_buffer.clear()
                                    commands.command_handler(deferred)
                                    listener.reset()
                                    continue
                            
                            # Mode 1: wake-word + команда в одной фразе
                            command_part = text.lower().replace(wake_word, "").strip(".,!?:; ")
                            if command_part:
                                log_message(f"Mode 1 (Мгновенный): '{command_part}'", "FriDay.py")
                                query = (command_part
                                    .replace("пятницу", "пятница")
                                    .replace("завершил работу", "заверши работу")
                                    .replace("перезагрузить компьютер", "перезагрузи компьютер"))
                                commands.command_handler(query)
                                listener.reset()
                                continue
                            
                            # Mode 2: только wake-word → ожидание команды
                            log_message("Mode 2 (Ожидание): переход в режим команд", "FriDay.py")
                            _activate_listening_mode()
                            listener.reset()
                    else:
                        # Mode 3: текст без wake-word → отложенный вопрос
                        if commands.memory_buffer:
                            commands.memory_buffer.update(text)
                            commands.memory_buffer.mark_deferred()
                
            except Exception as e:
                log_message(f"Ошибка при чтении/обработке аудио в WWD: {e}", "FriDay.py")
                time.sleep(0.05)
                continue
    
    except KeyboardInterrupt:
        log_message("Прерывание с клавиатуры", "FriDay.py")
    except Exception as e:
        log_message(f"Исключение в wwd(): {e}", "FriDay.py")
    finally:
        cleanup_audio()


def start():
    """Запуск основного цикла."""
    log_message("Запуск иконки в системном трее...", "FriDay.py")
    init_hotbar(commands.shutdown_event, os.getpid())
    hotbar_thread = start_hotbar()

    if hotbar_thread:
        log_message(f"Иконка запущена в потоке: {hotbar_thread.name}", "FriDay.py")
    else:
        log_message("Не удалось запустить иконку в трее", "FriDay.py")

    log_message("Запускается WWD поток", "FriDay.py")
    WWD()


if __name__ == "__main__":
    start()

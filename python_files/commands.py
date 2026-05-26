import os
import re
import time
import subprocess
import threading

from num2words import num2words

from python_files.constants import BASE_DIR
from python_files.logger import log_message
from python_files import settings
from python_files.FriDay_say import FriDay_say_
from python_files.tts import speak
from python_files.number_utils import extract_number_from_query, extract_time_from_query, get_hour_word, get_minute_word
from python_files.calc import calc_command
from python_files.brightness import adjust_brightness, reset_brightness, set_absolute_brightness, extract_brightness_value
from python_files.search import search_web
from python_files.text_normalization import normalize_text

ans = None
shutdown_event = threading.Event()
alarm_time = None
timer_end_time = None

memory_buffer = None


class MemoryBuffer:
    def __init__(self, ttl=120):
        self.phrase = None
        self.timestamp = 0
        self.deferred = None
        self.deferred_ts = 0
        self.ttl = ttl

    def update(self, text):
        self.phrase = text
        self.timestamp = time.time()

    def get(self):
        if self.phrase is not None and time.time() - self.timestamp <= self.ttl:
            return self.phrase
        return None

    def mark_deferred(self):
        if self.phrase is not None:
            self.deferred = self.phrase
            self.deferred_ts = self.timestamp

    def get_deferred(self):
        if self.deferred is not None and time.time() - self.deferred_ts <= self.ttl:
            return self.deferred
        return None

    def clear(self):
        self.phrase = None
        self.timestamp = 0
        self.deferred = None
        self.deferred_ts = 0


def init_memory_buffer(ttl=120):
    global memory_buffer
    memory_buffer = MemoryBuffer(ttl)


def command_handler(query):
    """Обрабатывает распознанную команду пользователя"""
    global ans, alarm_time, timer_end_time
    
    if query == "повтори":
        log_message(f"Обработка команды: {query}", "commands.py")
        if ans:
            speak(ans)
        else:
            speak("Я ещё ничего не говорила")
    elif any(cmd in query for cmd in ["выключи компьютер", "выключи систему", "заверши работу компьютера"]):
        log_message(f"Обработка команды: {query}", "commands.py")
        try:
            subprocess.run(['systemctl', 'poweroff'], check=True)
        except Exception as e:
            log_message(f"Ошибка выключения системы: {e}", "commands.py")
    elif any(cmd in query for cmd in ["заверш", "выключись", "остановись"]) or query in ["пятница выключись", "заверши работу"]:
        log_message(f"Обработка команды: {query}", "commands.py")
        path = os.path.join(BASE_DIR, "FriDay_say", "i_am_doing.wav")
        FriDay_say_(path)
        settings.cleanup()
        from python_files.FriDay_say import cleanup_pyaudio
        cleanup_pyaudio()
        os._exit(0)
    elif "поставь будильник на" in query or "будильник на" in query:
        log_message(f"Обработка команды: {query}", "commands.py")
        
        hours, minutes = extract_time_from_query(query)
        
        if hours is not None and 0 <= hours <= 23 and 0 <= minutes <= 59:
            current_time = time.localtime()
            new_alarm_time = time.mktime((
                current_time.tm_year,
                current_time.tm_mon,
                current_time.tm_mday,
                hours,
                minutes,
                0, 0, 0, 0
            ))
            
            if new_alarm_time <= time.time():
                new_alarm_time += 24 * 3600
            
            alarm_time = new_alarm_time
            
            hours_words = num2words(hours, lang='ru')
            hour_word = get_hour_word(hours)
            
            if minutes == 0:
                speak(f"Будильник установлен на {hours_words} {hour_word}")
            else:
                minutes_words = num2words(minutes, lang='ru')
                minute_word = get_minute_word(minutes)
                speak(f"Будильник установлен на {hours_words} {hour_word} {minutes_words} {minute_word}")
            return
        else:
            speak("Скажите полностью, например: будильник на пять часов тридцать минут")
    elif "таймер на" in query:
        log_message(f"Обработка команды: {query}", "commands.py")
        
        try:
            minutes = extract_number_from_query(query)
            
            if minutes is None:
                ans = "Не удалось распознать время для таймера"
                speak(ans)
                return ans
                
            timer_end_time = time.time() + minutes * 60
            minutes_words = num2words(minutes, lang='ru')
            minute_word = get_minute_word(minutes)
            ans = f"Таймер установлен на {minutes_words} {minute_word}"
            speak(ans)
            return ans
        except Exception as e:
            log_message(f"Ошибка в таймере: {e}", "commands.py")
            ans = "Не удалось распознать время для таймера"
            speak(ans)
            return ans
    elif "таймер" in query and any(word in query for word in ["останов", "отмен", "стоп", "выключи"]):
        if timer_end_time is not None:
            timer_end_time = None
            log_message("Таймер остановлен", "commands.py")
            speak("Таймер остановлен")
        else:
            speak("Таймер не запущен")
    elif any(word in query for word in ["сколько", "посчитай", "калькулятор"]) or \
         any(op in query for op in ["плюс", "минус", "умнож", "делен", "нацело", "остаток", "в степени", "корень", "квадрат"]):
        log_message(f"Обработка калькулятора: {query}", "commands.py")
        ans = calc_command(query)
        return ans
    elif "яркост" in query:
        log_message(f"Обработка яркости: {query}", "commands.py")
        if any(w in query for w in ["стандарт", "обычн", "нормаль", "сброс"]):
            reset_brightness(query)
            ans = "Яркость сброшена до стандартной"
            speak(ans)
            return ans
        elif any(w in query for w in ["увелич", "прибав", "добав", "повыс", "больше"]):
            delta = extract_brightness_value(query)
            if delta:
                adjust_brightness(query, delta)
                ans = "Яркость увеличена"
            else:
                ans = "На сколько увеличить?"
            speak(ans)
            return ans
        elif any(w in query for w in ["уменьш", "убав", "сниз", "меньше"]):
            delta = extract_brightness_value(query)
            if delta:
                adjust_brightness(query, -delta)
                ans = "Яркость уменьшена"
            else:
                ans = "На сколько уменьшить?"
            speak(ans)
            return ans
        else:
            val = extract_brightness_value(query)
            if val:
                set_absolute_brightness(query, val)
                ans = "Яркость установлена"
            else:
                ans = "Не поняла, какую яркость поставить"
            speak(ans)
            return ans
    elif "посмотр" in query:
        log_message(f"Обработка команды: {query}", "commands.py")
        search_query = re.sub(r'\bпосмотр(и|еть|ите|им)\b', '', query, flags=re.IGNORECASE).strip()
        search_query = re.sub(r'\b(в интернете|в гугл|в гугле|в яндексе|на сайте|информацию)\b', '', search_query, flags=re.IGNORECASE).strip()
        if not search_query:
            speak("Что мне найти?")
        else:
            result = search_web(search_query)
            if result:
                result = normalize_text(result)
                ans = result
                speak(ans)
            else:
                ans = "Не удалось найти информацию"
                speak(ans)
        return ans

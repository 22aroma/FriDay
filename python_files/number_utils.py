"""
Утилиты для работы с числами и извлечения чисел из текста
"""

import re


def extract_number_from_query(query, default=None):
    query_lower = query.lower()
    
    numbers = re.findall(r'\b\d+\b', query_lower)
    if numbers:
        return int(numbers[0])
    
    return default


def extract_time_from_query(query):
    query_lower = query.lower()
    
    time_match = re.search(r'\b(\d{1,2}):(\d{2})\b', query_lower)
    if time_match:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return hours, minutes
    
    words = query_lower.split()
    
    hours = None
    minutes = 0
    
    hour_markers = ['час', 'часов', 'часа']
    minute_markers = ['минут', 'минуты', 'минута']
    
    for i, word in enumerate(words):
        if word in hour_markers and i > 0:
            prev_word = words[i-1]
            if prev_word.isdigit():
                hours = int(prev_word)
    
    for i, word in enumerate(words):
        if word in minute_markers and i > 0:
            prev_word = words[i-1]
            if prev_word.isdigit():
                minutes = int(prev_word)
    
    return hours, minutes


def get_hour_word(hours):
    if hours % 10 == 1 and hours % 100 != 11:
        return "час"
    elif hours % 10 in [2, 3, 4] and hours % 100 not in [12, 13, 14]:
        return "часа"
    else:
        return "часов"


def get_minute_word(minutes):
    if minutes % 10 == 1 and minutes % 100 != 11:
        return "минуту"
    elif minutes % 10 in [2, 3, 4] and minutes % 100 not in [12, 13, 14]:
        return "минуты"
    else:
        return "минут"

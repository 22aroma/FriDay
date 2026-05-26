# Пятница (FriDay)

Голосовой ассистент с распознаванием речи на русском языке, синтезом речи и
пробуждением по голосу ("Пятница").

![Python](https://img.shields.io/badge/python-3.14-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)

## Возможности

- **Пробуждение по голосу** — Wake Word Detection "Пятница" с Silero VAD
- **Распознавание речи** — Kairos ASR (офлайн)
- **Синтез речи** — Silero TTS (голос *baya*)
- **Будильник** — голосовая установка
- **Таймер** — с возможностью отмены
- **Калькулятор** — голосовые вычисления (+, -, *, /, %, корень, степень)
- **Яркость экрана** — управление через xrandr
- **Поиск в интернете** — DuckDuckGo
- **Выключение компьютера** — голосовая команда
- **Системный трей** — иконка в трее для управления
- **Отложенные вопросы** — 120-секундный буфер контекста

## Команды

| Фраза | Действие |
|---|---|
| *Пятница, сколько будет 2 плюс 2* | Калькулятор |
| *Пятница, поставь будильник на 7 часов* | Будильник |
| *Пятница, таймер на 5 минут* | Таймер |
| *Пятница, увеличь яркость* | Яркость экрана |
| *Пятница, посмотри погоду в интернете* | Поиск в DuckDuckGo |
| *Пятница, выключи компьютер* | Выключение системы |
| *Пятница, заверши работу* | Выход из ассистента |
| *Пятница* (без команды) | Режим ожидания команды на 15 с |

## Структура проекта

```
FriDay/
├── FriDay.pyw                          # Точка входа
├── python_files/
│   ├── __init__.py
│   ├── constants.py                    # Константы (пути, аудио, TTS)
│   ├── logger.py                       # Логирование
│   ├── settings.py                     # Инициализация аудиопотока
│   ├── stt.py                          # Распознавание речи (VAD + ASR)
│   ├── tts.py                          # Синтез речи (Silero TTS)
│   ├── FriDay_say.py                   # Воспроизведение WAV
│   ├── commands.py                     # Обработчик команд
│   ├── search.py                       # Поиск в DuckDuckGo
│   ├── calc.py                         # Калькулятор
│   ├── brightness.py                   # Яркость экрана (xrandr)
│   ├── text_normalization.py           # Нормализация русского текста
│   ├── number_utils.py                 # Извлечение чисел/времени
│   ├── lists.py                        # Списки слов 
│   └── tray_icon.py                    # Иконка в системном трее
├── files/
│   └── icon.png                        # Иконка трея
├── FriDay_say/
│   ├── i_am_doing.wav                  # Звук выполнения
│   └── wwd/
│       └── listen.wav                  # Звук ожидания команды
├── requirements.txt                    # Все зависимости
├── setup_venv.sh                       # Скрипт настройки (Arch Linux)
├── log.txt                             # Файл лога
└── LICENSE                             # MIT License
```

## Установка

### Зависимости системы (Arch Linux)

```bash
sudo pacman -S python python-pip portaudio xorg-xrandr
```

### Установка зависимостей

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Установка PyTorch (CPU)

```bash
pip install --index-url https://download.pytorch.org/whl/cpu torch==2.12.0+cpu
```

### Альтернатива — скрипт настройки

```bash
chmod +x setup_venv.sh
./setup_venv.sh
```

## Запуск

```bash
source venv/bin/activate
python FriDay.pyw
```

При первом запуске будут загружены и закешированы модели:
- Silero VAD (`snakers4/silero-vad`)
- Silero TTS (`snakers4/silero-models`)
- Kairos ASR (скачивается в `~/.cache/`)

## Зависимости

Полный список — в [requirements.txt](requirements.txt).
Ключевые пакеты:

| Пакет | Назначение |
|---|---|
| PyAudio | Захват аудио с микрофона |
| sounddevice | Воспроизведение аудио |
| torch + torchaudio | Нейросетевые модели |
| kairos-asr | Распознавание русской речи |
| silero-vad / silero-models | Детекция речи и синтез |
| num2words | Числа прописью (русский) |
| pystray + pillow | Иконка в системном трее |
| ddgs | Поиск в DuckDuckGo |
| onnxruntime | Инференс ONNX-моделей |

## Особенности

- **Только Linux** — использует xrandr и systemctl
- **Русский язык** — весь интерфейс и голосовые ответы на русском
- **Офлайн** — после загрузки моделей не требует интернета (кроме поиска)
- **Атрибуты** — ключевое слово "Пятница", женский голос

## Лицензия

MIT License. Copyright (c) 2026 Aroma.

Подробнее:
- [LICENSE](LICENSE) — полный текст лицензии MIT
- [ATTRIBUTION.md](ATTRIBUTION.md) — информация о сторонних библиотеках и их лицензиях

## Благодарность
- Иконка для системного трея предоставлена [Icons8](https://icons8.com)

**Проект создан в учебных целях.**

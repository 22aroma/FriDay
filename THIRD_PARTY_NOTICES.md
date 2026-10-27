# Third-Party Notices

FriDay использует следующие сторонние компоненты. Полные тексты лицензий
доступны по ссылкам и в пакетах, устанавливаемых через `pip`.

## Зависимости

| Компонент | Лицензия | Ссылка |
|---|---|---|
| PyTorch, torchaudio | BSD-3-Clause | https://github.com/pytorch/pytorch |
| transcribe-cpp | MIT | https://github.com/handy-computer/transcribe.cpp |
| Hugging Face Hub | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| SciPy | BSD-3-Clause | https://github.com/scipy/scipy |
| OmegaConf | BSD-3-Clause | https://github.com/omry/omegaconf |
| onnxruntime | MIT | https://github.com/microsoft/onnxruntime |
| Pillow | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| requests | Apache-2.0 | https://github.com/psf/requests |
| sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice |
| CustomTkinter | MIT | https://github.com/TomSchimansky/CustomTkinter |
| num2words | LGPL-2.1-or-later | https://github.com/savoirfairelinux/num2words |
| PyAV (`av`) | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| yt-dlp | Unlicense | https://github.com/yt-dlp/yt-dlp |
| FFmpeg (через PyAV) | LGPL-2.1-or-later | https://ffmpeg.org/legal.html |

`pystray` и `num2words` распространяются под LGPL и используются как отдельные
динамически подключаемые зависимости, без изменения их исходного кода.

PyAV может поставляться со сборкой FFmpeg под LGPL (или GPL — зависит от
конкретного wheel). Если вы распространяете собранное приложение с этими
библиотеками, добавьте уведомления LGPL/GPL и обеспечьте возможность замены
библиотек, как того требует соответствующая лицензия.

## Установщик

`FriDay.exe` собирается через PyInstaller и использует PyYAML для чтения и
записи `files/config.yml`.

| Компонент | Лицензия | Ссылка |
|---|---|---|
| PyInstaller | GPL-2.0-or-later с исключением для bootloader | https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt |
| PyYAML | MIT | https://github.com/yaml/pyyaml |

Исключение в лицензии PyInstaller разрешает распространять собранные с его
помощью приложения под любой лицензией; сам PyInstaller в код приложения не
входит и нужен только на этапе сборки.

## Модели

Модели не входят в репозиторий и скачиваются пользователем отдельно.

| Модель | Лицензия | Ссылка |
|---|---|---|
| Silero VAD | MIT | https://github.com/snakers4/silero-vad |
| Silero TTS `v5_4_ru` (голос `baya`) | **CC BY-NC 4.0** (некоммерческая) | https://github.com/snakers4/silero-models |
| GigaAM-v3 e2e RNNT GGUF | MIT | https://huggingface.co/handy-computer/gigaam-v3-e2e-rnnt-gguf |
| GigaAM (исходные модели) | MIT | https://github.com/salute-developers/GigaAM |

Silero TTS `v5_4_ru` — некоммерческая модель. Это ограничивает коммерческое
использование приложения «из коробки». Код проекта при этом распространяется
под MIT.

## Шрифт

**Martian Mono** — SIL Open Font License 1.1.
Copyright 2021 The Martian Mono Project Authors
(https://github.com/evilmartians/mono).
Текст лицензии: `files/fonts/OFL.txt`.

## Иконка

Иконка приложения (`files/icon.ico`) создана автором проекта.

## Python

Python распространяется под PSF License Agreement:
https://docs.python.org/3/license.html

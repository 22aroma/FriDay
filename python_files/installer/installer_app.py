import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

_T0 = time.monotonic()

APP_NAME = "FriDay"
REPO = "22aroma/FriDay"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
TORCH_VERSION = "2.10.0"

BG = "#15171c"
SURFACE = "#1e2128"
SURFACE2 = "#242833"
BORDER = "#2c313b"
TXT = "#e7eaee"
SUB = "#8b93a1"
LABEL = "#b9c2cf"
ACCENT = "#7da2ff"
DANGER = "#e0655f"
OK = "#69b98c"
LOG_BG = "#101216"
LOG_TXT = "#c9d2de"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

def _detect_base(start: Path) -> Path:
    p = start
    for _ in range(5):
        if (p / f"{APP_NAME}.pyw").exists():
            return p
        parent = p.parent
        if parent == p:
            break
        p = parent
    return start


if getattr(sys, "frozen", False):
    BASE_DIR = _detect_base(Path(sys.executable).parent)
else:
    BASE_DIR = _detect_base(Path(__file__).resolve().parent)

VENV_DIR = BASE_DIR / "venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
VENV_PYW = VENV_DIR / "Scripts" / "pythonw.exe"
SCRIPT_PATH = BASE_DIR / f"{APP_NAME}.pyw"
MODELS_SCRIPT = BASE_DIR / "files" / "download_models.py"
CONFIG_PATH = BASE_DIR / "files" / "config.yml"
STARTUP_LNK = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
    / f"{APP_NAME}.lnk"
)

if getattr(sys, "frozen", False):
    ICON_PATH = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "icon.ico"
    BUNDLED_FONT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "MartianMono.ttf"
else:
    ICON_PATH = BASE_DIR / "files" / "icon.ico"
    BUNDLED_FONT = BASE_DIR / "files" / "fonts" / "MartianMono.ttf"


_FR_PRIVATE = 0x10


def register_bundled_font() -> bool:
    if not BUNDLED_FONT.exists():
        return False
    try:
        import ctypes

        _gdi32 = ctypes.windll.gdi32
        _gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        _gdi32.AddFontResourceExW.restype = ctypes.c_int
        return _gdi32.AddFontResourceExW(str(BUNDLED_FONT), _FR_PRIVATE, None) > 0
    except Exception:
        return False


def remove_bundled_font() -> None:
    if not BUNDLED_FONT.exists():
        return
    try:
        import ctypes

        _gdi32 = ctypes.windll.gdi32
        _gdi32.RemoveFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        _gdi32.RemoveFontResourceExW(str(BUNDLED_FONT), _FR_PRIVATE, None)
    except Exception:
        pass

LOG_Q = queue.Queue()


def ui_log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    LOG_Q.put(("ln", (ts, str(msg))))


class UiLogRouter:
    def __init__(self, mirror):
        self._mirror = mirror
        self._buf = ""

    def write(self, s):
        if self._mirror is not None:
            try:
                self._mirror.write(s)
                self._mirror.flush()
            except Exception:
                pass
        if not s:
            return len(s)
        self._buf += s.replace("\r\n", "\n")
        while True:
            m = re.search(r"[\n\r]", self._buf)
            if not m:
                break
            seg = self._buf[: m.start()]
            sep = self._buf[m.start()]
            self._buf = self._buf[m.end() :]
            t = seg.strip()
            if t:
                kind = "cr" if sep == "\r" else "ln"
                LOG_Q.put((kind, (datetime.now().strftime("%H:%M:%S"), t)))
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


def install_output_router():
    mirror_out = None if isinstance(sys.stdout, UiLogRouter) else sys.stdout
    mirror_err = None if isinstance(sys.stderr, UiLogRouter) else sys.stderr
    sys.stdout = UiLogRouter(mirror_out)
    sys.stderr = UiLogRouter(mirror_err)


def run_quiet(cmd: list, cwd: Path | None = None) -> int:
    return subprocess.call(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def find_python() -> list | None:
    for cmd in (["python"], ["py", "-3"]):
        try:
            r = subprocess.run(
                cmd + ["--version"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=8,
            )
        except Exception:
            continue
        if r.returncode == 0 and "Python 3" in r.stdout + r.stderr:
            return cmd
    return None


def _friday_pids() -> list[int]:
    """PID всех запущенных процессов FriDay (pythonw … FriDay.pyw)."""
    ps = (
        "(Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like '*FriDay.pyw*' } | "
        "Select-Object -ExpandProperty ProcessId) -join ','"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (r.stdout or "").strip()
        return [int(x) for x in out.split(",") if x.strip().isdigit()]
    except Exception:
        return []


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс по PID (без запуска shell-команд)."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def stop_friday() -> None:
    """Завершаем все экземпляры FriDay и ждём, пока они реально умрут."""
    pids = _friday_pids()
    if not pids:
        return
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    deadline = time.time() + 6
    while time.time() < deadline:
        if not any(_pid_alive(pid) for pid in pids):
            return
        time.sleep(0.2)


def download_zipball(dest: Path) -> None:
    import requests

    url = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
    headers = {
        "User-Agent": "FriDay-installer",
    }

    # split (connect, read) timeouts: connect fails fast instead of hanging
    # silently for minutes on a blocked/throttled network.
    connect_timeout, read_timeout = 15, 60

    def _one_attempt():
        with requests.get(url, headers=headers, stream=True, timeout=(connect_timeout, read_timeout)) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Download failed (HTTP {r.status_code})")
            total = int(r.headers.get("content-length", 0))

            def mb(n):
                return n / 1024 / 1024

            done = 0
            t0 = time.time()
            last = None
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    out = (
                        f"\r  {done * 100 // total}% ({mb(done):.1f}/{mb(total):.1f} MB)"
                        if total
                        else f"\r  {mb(done):.1f} MB"
                    )
                    if out != last or time.time() - t0 >= 0.5:
                        last = out
                        t0 = time.time()
                        sys.stdout.write(out)
                        sys.stdout.flush()
            if done:
                sys.stdout.write("\r  100% download complete.\n")

    print(f"Downloading {REPO} archive...")
    for attempt in range(1, 4):
        print(f"  [attempt {attempt}] connecting to GitHub...")
        try:
            _one_attempt()
            return
        except Exception as ex:
            if attempt < 3:
                print(f"\n  Connection error (attempt {attempt}/3): {ex}. Retrying...")
                time.sleep(2)
            else:
                raise RuntimeError(f"Download failed after 3 attempts: {ex}") from ex


def copy_project(src_dir: Path) -> None:
    skip_if_exists = ("log.txt",)
    always_skip = ("config.yml", "Install-Update.bat")
    keep_files = ("config.yml", "presets.json")

    def is_skipped(name: str, exists: bool) -> bool:
        if name == "venv":
            return True
        if name in always_skip:
            return True
        if name.startswith("Install") and (name.endswith(".bat") or name.endswith(".sh")):
            return exists
        if name in skip_if_exists and exists:
            return True
        if getattr(sys, "frozen", False) and name == Path(sys.executable).name:
            return True
        return False

    count = 0
    print(f"Copying project files to {BASE_DIR}...")
    for item in src_dir.iterdir():
        dest = BASE_DIR / item.name
        if is_skipped(item.name, dest.exists()):
            continue
        if item.is_dir():
            backups = {}
            if item.name == "files":
                for name in keep_files:
                    src = dest / name
                    if src.exists():
                        bak = Path(tempfile.mktemp(prefix=f"{name}_bak_"))
                        shutil.copy2(src, bak)
                        backups[name] = bak
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(item, dest, dirs_exist_ok=True)
            for cc in dest.rglob("__pycache__"):
                shutil.rmtree(cc, ignore_errors=True)
            for pyc in dest.rglob("*.pyc"):
                try:
                    pyc.unlink()
                except Exception:
                    pass
            for name, bak in backups.items():
                shutil.copy2(bak, dest / name)
                bak.unlink(missing_ok=True)
        else:
            shutil.copy2(item, dest)
        count += 1
    print(f"Copied {count} items.")


def fetch_and_copy() -> None:
    tmp_root = Path(tempfile.mkdtemp(prefix="FriDay_installer_"))
    zip_path = tmp_root / "FriDay.zip"
    extract_dir = tmp_root / "extract"
    try:
        download_zipball(zip_path)
        print("Extracting...")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)
        src_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        if not src_dirs:
            raise RuntimeError("Archive structure unexpected")
        stop_friday()
        copy_project(src_dirs[0])
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def stream_process(cmd: list, cwd: Path | None = None, env_extra: dict | None = None) -> int:
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PIP_PROGRESS_BAR": "on",
        # Дочерний процесс пишет в пайп в кодировке локали (cp1251), а читаем мы
        # его как UTF-8 — без этого русские сообщения превращаются в кракозябры.
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    if env_extra:
        env.update(env_extra)
    print(f"> {' '.join(cmd)}")
    import codecs

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        while True:
            chunk = proc.stdout.read1(8192)
            if not chunk:
                break
            text = dec.decode(chunk)
            if text:
                sys.stdout.write(text)
                sys.stdout.flush()
        tail = dec.decode(b"", final=True)
        if tail.strip():
            sys.stdout.write(tail)
    finally:
        rc = proc.wait()
    print(f"Exit code: {rc}")
    return rc


def cleanup_venv_bloat() -> None:
    torch_pkg = VENV_DIR / "Lib" / "site-packages" / "torch"
    if torch_pkg.exists():
        for sub in ("test", "include", "onnx", "_inductor", "_dynamo"):
            shutil.rmtree(torch_pkg / sub, ignore_errors=True)
    for root, dirs, _files in os.walk(VENV_DIR):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(Path(root) / d, ignore_errors=True)
                dirs.remove(d)
    run_quiet([str(VENV_PY), "-m", "pip", "cache", "purge"])


def _pip_install(pip_args: list) -> int:
    rc = stream_process([str(VENV_PY), "-m", "pip", "install"] + pip_args)
    if rc != 0:
        print("Retrying without cache...")
        rc = stream_process([str(VENV_PY), "-m", "pip", "install", "--no-cache-dir"] + pip_args)
    return rc


def do_install_venv() -> None:
    py_cmd = find_python()
    if not py_cmd:
        raise RuntimeError("Python 3 not found. Install Python 3.11+ with 'Add to PATH'.")
    print("Creating virtual environment...")
    if VENV_DIR.exists():
        print("Removing old venv...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    rc = subprocess.call(py_cmd + ["-m", "venv", str(VENV_DIR)], creationflags=CREATE_NO_WINDOW)
    if rc != 0 or not VENV_PY.exists():
        raise RuntimeError("Failed to create virtual environment.")
    print(f"Installing torch {TORCH_VERSION} (CPU)...")
    torch_req = ["--index-url", TORCH_INDEX, f"torch=={TORCH_VERSION}", f"torchaudio=={TORCH_VERSION}"]
    if _pip_install(torch_req) != 0:
        raise RuntimeError("Torch installation failed.")
    print("Installing dependencies...")
    if _pip_install(["-r", str(BASE_DIR / "files" / "requirements.txt")]) != 0:
        raise RuntimeError("Dependencies installation failed.")
    print("Cleaning up...")
    cleanup_venv_bloat()
    print("Virtual environment installed.")


def autostart_enabled() -> bool:
    return STARTUP_LNK.exists()


def toggle_autostart() -> None:
    if autostart_enabled():
        STARTUP_LNK.unlink(missing_ok=True)
        print("Autostart disabled.")
        return
    if not VENV_PYW.exists():
        raise RuntimeError("Install the project first.")
    STARTUP_LNK.parent.mkdir(parents=True, exist_ok=True)
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{STARTUP_LNK}'); "
        f"$sc.TargetPath = '{VENV_PYW}'; "
        f"$sc.Arguments = '\"{SCRIPT_PATH}\"'; "
        f"$sc.WorkingDirectory = '{BASE_DIR}'; "
        "$sc.WindowStyle = 7; "
        "$sc.Save()"
    )
    rc = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
    ).returncode
    if rc != 0 or not STARTUP_LNK.exists():
        raise RuntimeError("Failed to create autostart shortcut.")
    print("Autostart enabled.")


def run_friday() -> None:
    if not VENV_PYW.exists() or not SCRIPT_PATH.exists():
        raise RuntimeError("Install the project first.")
    stop_friday()
    proc = subprocess.Popen(
        [str(VENV_PYW), str(SCRIPT_PATH)],
        cwd=str(BASE_DIR),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    print("FriDay запускается, подождите пару секунд...")
    deadline = time.time() + 4
    while time.time() < deadline:
        if not _pid_alive(proc.pid):
            if _friday_pids():
                print("FriDay уже запущен (работает другой экземпляр).")
            else:
                print("Процесс завершился сразу после старта. Проверьте files/log.txt.")
            return
        time.sleep(0.25)
    print("FriDay запущен.")


def delete_caches() -> None:
    home = Path.home()
    for p in (
        home / ".cache" / "torch" / "hub",
        home / ".cache" / "huggingface" / "hub",
        home / "AppData" / "Local" / "pip" / "Cache",
    ):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    print("Cache deleted.")


def cleanup_mode(target: str) -> None:
    target_path = Path(target)
    time.sleep(2)
    try:
        STARTUP_LNK.unlink(missing_ok=True)
    except Exception:
        pass
    for attempt in range(15):
        try:
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=False)
            break
        except Exception:
            time.sleep(1)
    if target_path.exists():
        shutil.rmtree(target_path, ignore_errors=True)
    delete_caches()
    if getattr(sys, "frozen", False):
        self_dir = Path(sys.executable).parent
        subprocess.Popen(
            ["cmd", "/c", "timeout", "/t", "2", "/nobreak", ">nul", "&", "rmdir", "/s", "/q", f'"{self_dir}"'],
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        )


def initiate_full_delete(page) -> None:
    print("Removing FriDay...")
    stop_friday()
    if getattr(sys, "frozen", False):
        tmp_dir = Path(tempfile.gettempdir()) / f"FriDay_uninstall_{os.getpid()}"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        app_root = Path(sys.executable).parent
        shutil.copy2(sys.executable, tmp_dir / Path(sys.executable).name)
        shutil.copytree(
            app_root / "_internal", tmp_dir / "_internal",
            dirs_exist_ok=True,
        )
        tmp_exe = tmp_dir / Path(sys.executable).name
        subprocess.Popen(
            [str(tmp_exe), "--cleanup", str(BASE_DIR)],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            [sys.executable, __file__, "--cleanup", str(BASE_DIR)],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    time.sleep(0.5)
    try:
        page.destroy()
    except Exception:
        os._exit(0)


DEFAULT_CONFIG = '''# ============================================================
# FriDay — пользовательские настройки (files/config.yml)
# ============================================================
# Файл создаётся автоматически при сохранении настроек в
# установщике, если параметры отличаются от стандартных.
# Можно создать вручную и править в любом редакторе.
# После изменения сохраните файл и перезапустите FriDay.
# ============================================================

# --- Параметры аудио ---
audio:
  sample_rate: 16000       # Частота дискретизации микрофона (Гц)
  chunk: 4000              # Размер блока для чтения с микрофона

# --- Параметры распознавания речи (VAD + ASR) ---
speech:
  silence_threshold_ms: 300    # Сколько тишины нужно для конца фразы (мс)
  min_speech_duration_ms: 100  # Минимальная длина речи, которая считается командой (мс)
  pre_recording_buffer_ms: 300 # Буфер аудио перед началом речи (мс)
  vad_threshold_speech: 0.2    # Чувствительность VAD во время речи (0-1, ниже = чувствительнее)
  vad_threshold_silence: 0.3   # Чувствительность VAD вне речи (0-1, ниже = чувствительнее)
  noise_gate_enabled: true     # Включить шумовой гейт (фильтр фона/музыки перед VAD)
  noise_gate_factor: 2.5       # Множитель шумового фона ( выше = агрессивнее фильтрация )

# --- Параметры синтеза речи (TTS) ---
tts:
  language: ru             # Язык (ru, en, etc.)
  model_id: v5_4_ru        # Модель TTS
  sample_rate: 48000       # Частота дискретизации синтеза (Гц)
  speaker: baya            # Голос (baya, aidar, kseniya, xenia, eugene, etc.)

# --- Ключевое слово для активации ---
# ВАЖНО: при смене wake_word фразы-обращения к помощнику должны совпадать
# с этим словом. Подробнее см. в FriDay.pyw (нормализация ключевого слова).
wake_word: пятница

# --- Режим прослушивания команд ---
listening_duration: 15     # Сколько секунд ждать команду после активации
detection_cooldown: 1      # Минимальный интервал между активациями (сек)

# --- Память (для отложенных команд без ключевого слова) ---
memory_ttl: 60             # Сколько секунд хранить фразу без ключевого слова

# --- Погода ---
weather:
  default_city: Москва     # Город по умолчанию
  timeout: 5               # Таймаут HTTP-запроса (сек)
  api_key: ""              # Ключ OpenWeatherMap: https://openweathermap.org/api

# --- Музыка ---
music:
  default_genre: ""                     # Жанр по умолчанию ("включи музыку" без уточнения). Пусто = популярное

# --- Обои ---
wallpaper:
  path: ""                              # Папка с обоями (случайная картинка) или путь к одному файлу. "Смени обои" применит её на ВСЕХ рабочих столах
'''

CONFIG_SECTIONS = [
    (
        "Assistant",
        [
            (None, "wake_word", "Ключевое слово активации", "str"),
            (None, "listening_duration", "Ожидание команды после ключевого слова, сек", "int"),
            (None, "detection_cooldown", "Пауза между активациями, сек", "int"),
            (None, "memory_ttl", "Память отложенных команд, сек", "int"),
        ],
    ),
    (
        "Speech recognition",
        [
            ("speech", "silence_threshold_ms", "Тишина для конца фразы, мс", "int"),
            ("speech", "min_speech_duration_ms", "Минимальная длина команды, мс", "int"),
            ("speech", "pre_recording_buffer_ms", "Буфер до начала речи, мс", "int"),
            ("speech", "vad_threshold_speech", "Порог VAD в речи (0–1)", "float"),
            ("speech", "vad_threshold_silence", "Порог VAD в тишине (0–1)", "float"),
            ("speech", "noise_gate_enabled", "Шумовой гейт (фильтр фона)", "bool"),
            ("speech", "noise_gate_factor", "Множитель шумового фона", "float"),
        ],
    ),
    (
        "Voice",
        [
            ("tts", "language", "Язык озвучки (ru, en…)", "str"),
            ("tts", "model_id", "Модель TTS", "str"),
            ("tts", "speaker", "Голос (baya, aidar, kseniya, xenia, eugene)", "str"),
            ("tts", "sample_rate", "Частота синтеза, Гц", "int"),
        ],
    ),
    (
        "Audio input",
        [
            ("audio", "sample_rate", "Частота микрофона, Гц", "int"),
            ("audio", "chunk", "Размер блока чтения", "int"),
        ],
    ),
    (
        "Weather",
        [
            ("weather", "default_city", "Город по умолчанию", "str"),
            ("weather", "timeout", "Таймаут запроса, сек", "int"),
            ("weather", "api_key", "Ключ OpenWeatherMap", "str"),
        ],
    ),
    (
        "Music",
        [
            ("music", "default_genre", "Жанр по умолчанию (пусто = популярное)", "str"),
        ],
    ),
    (
        "Wallpaper",
        [
            ("wallpaper", "path", "Путь к папке обоев", "str"),
        ],
    ),
]


def _defaults_from_template() -> dict:
    import yaml

    data = yaml.safe_load(DEFAULT_CONFIG) or {}
    values = {}
    for _title, rows in CONFIG_SECTIONS:
        for sec, key, _label, kind in rows:
            if sec:
                values[(sec, key)] = data.get(sec, {}).get(key)
            else:
                values[(None, key)] = data.get(key)
    return values


def load_config_values() -> dict:
    import yaml

    try:
        text = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else DEFAULT_CONFIG
        data = yaml.safe_load(text) or {}
    except Exception:
        data = {}
    values = _defaults_from_template()
    for _title, rows in CONFIG_SECTIONS:
        for sec, key, _label, kind in rows:
            try:
                if sec:
                    v = data.get(sec, {}).get(key)
                else:
                    v = data.get(key)
                if v is not None:
                    values[(sec, key)] = v
            except Exception:
                pass
    return values


def _format_yaml_value(kind: str, raw: str):
    if kind == "int":
        return int(raw.strip())
    if kind == "float":
        return float(raw.strip().replace(",", "."))
    if kind == "bool":
        return raw.strip().lower() in ("true", "1", "yes", "да")
    v = raw.strip()
    return v


def _dump_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "":
        return '""'
    needs_quotes = (
        re.search(r"""[:#'"{}\[\],&*?|>%@`\n]""", s)
        or s != s.strip()
        or re.fullmatch(r"-?\d+(\.\d+)?", s)
        or s.lower() in ("true", "false", "null", "yes", "no")
    )
    if needs_quotes:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def save_config_values(new_values: dict) -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else DEFAULT_CONFIG
    lines = text.splitlines()

    def fmt_line_value(key: str, tail: str, v) -> str:
        comment = ""
        idx = tail.find("#")
        if idx >= 0 and (idx == 0 or tail[idx - 1] in " \t"):
            comment = tail[idx:].strip()
        suffix = f"   {comment}" if comment else ""
        return f"{key}: {_dump_scalar(v)}{suffix}"

    section_re = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(?:#.*)?$")
    key_re = re.compile(r"^(\s*)([A-Za-z_][\w-]*)\s*:(.*)$")

    found = set()
    section_ends = {}
    current_sec = None
    for i, line in enumerate(lines):
        km = key_re.match(line)
        sm = section_re.match(line)
        if sm:
            current_sec = sm.group(1)
            continue
        if km and (km.group(1) == "" or current_sec is not None):
            _, k, tail = km.group(1), km.group(2), km.group(3)
            sec_scope = None if km.group(1) == "" else current_sec
            for (sec, key), v in new_values.items():
                if sec == sec_scope and key == k:
                    lead = "" if sec_scope is None else km.group(1)
                    lines[i] = lead + fmt_line_value(k, tail, v)
                    found.add((sec, key))
            if km.group(1):
                section_ends[current_sec] = i
    missing_by_sec = {}
    for (sec, key), v in new_values.items():
        if (sec, key) not in found:
            missing_by_sec.setdefault(sec, []).append((key, v))
    for sec, items in reversed(list(missing_by_sec.items())):
        if sec is None:
            for key, v in items:
                lines.append(fmt_line_value(key, "", v))
        elif sec in section_ends:
            pos = section_ends[sec]
            for j, (key, v) in enumerate(items):
                lines.insert(pos + 1 + j, f"  {fmt_line_value(key, '', v)}")
        else:
            lines.append(f"{sec}:")
            for key, v in items:
                lines.append(f"  {fmt_line_value(key, '', v)}")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_ui():
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    try:
        ctk.set_default_color_theme("dark-blue")
    except Exception:
        pass

    register_bundled_font()
    t_ctk = time.monotonic()

    FONT = "Martian Mono"

    def F(size, weight="normal"):
        return ctk.CTkFont(family=FONT, size=size, weight=weight)

    win = ctk.CTk()
    try:
        import tkinter.font as _tkfont

        if FONT not in _tkfont.families(root=win):
            FONT = "Segoe UI"
    except Exception:
        pass
    win.title(APP_NAME)
    t_win = time.monotonic()
    win.geometry("960x700")
    win.minsize(800, 580)
    try:
        win.configure(fg_color=BG)
        if ICON_PATH.exists():
            win.iconbitmap(bitmap=str(ICON_PATH))
    except Exception:
        pass

    if os.environ.get("FRIDAY_INSTALLER_DEBUG"):
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

    state = {"busy": False, "name": None, "t0": 0.0}

    win.grid_columnconfigure(0, weight=1)
    win.grid_rowconfigure(1, weight=1)
    win.grid_rowconfigure(0, weight=0)

    # ─── Навигация (вкладки) ────────────────────────────────────────────────

    nav = ctk.CTkFrame(win, fg_color=BG, corner_radius=0)
    nav.grid(row=0, column=0, sticky="nsew")
    nav.grid_columnconfigure(0, weight=1)
    nav.grid_columnconfigure(1, weight=1)
    nav.grid_columnconfigure(2, weight=1)

    content = ctk.CTkFrame(win, fg_color=BG)
    content.grid(row=1, column=0, sticky="nsew")
    content.grid_rowconfigure(0, weight=1)
    content.grid_columnconfigure(0, weight=1)

    installer_win = ctk.CTkFrame(content, fg_color=BG)
    settings_win = ctk.CTkFrame(content, fg_color=BG)
    presets_win = ctk.CTkFrame(content, fg_color=BG)
    tab_frames = [installer_win, settings_win, presets_win]
    for _f in tab_frames:
        _f.grid(row=0, column=0, sticky="nsew")

    tab_btns = []
    tab_under = []

    def show_tab(idx):
        for i, _f in enumerate(tab_frames):
            if i == idx:
                _f.grid()
            else:
                _f.grid_remove()
        for i, (b, u) in enumerate(zip(tab_btns, tab_under)):
            b.configure(text_color=(TXT if i == idx else SUB))
            u.configure(fg_color=(ACCENT if i == idx else "transparent"))

    for i, label in enumerate(("Установка", "Настройки", "Пресеты")):
        cell = ctk.CTkFrame(nav, fg_color="transparent")
        cell.grid(row=0, column=i, sticky="nsew")
        b = ctk.CTkButton(
            cell, text=label, fg_color="transparent", hover_color=SURFACE,
            text_color=SUB, corner_radius=0, height=46,
            font=F(15, "bold"), command=lambda idx=i: show_tab(idx),
        )
        b.pack(fill="x", side="top")
        u = ctk.CTkFrame(cell, height=3, fg_color="transparent", corner_radius=0)
        u.pack(fill="x", side="bottom")
        tab_btns.append(b)
        tab_under.append(u)

    divider = ctk.CTkFrame(nav, height=1, fg_color=BORDER, corner_radius=0)
    divider.grid(row=1, column=0, columnspan=3, sticky="ew")

    show_tab(0)

    # ─── Лог и очередь ──────────────────────────────────────────────────────

    log_lines = []
    log_box = ctk.CTkTextbox(
        installer_win,
        font=F(12),
        text_color=LOG_TXT, fg_color=LOG_BG,
        border_width=1, border_color=BORDER, corner_radius=10,
        wrap="word",
    )
    log_box.configure(state="disabled")

    def _set_log_text(text):
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.insert("1.0", text)
        log_box.see("end")
        log_box.configure(state="disabled")

    def apply_log_items(items):
        dirty = False
        ui_tasks = []
        for kind, ts_text in items:
            if kind == "ui":
                if callable(ts_text):
                    ui_tasks.append(ts_text)
                continue
            if isinstance(ts_text, tuple):
                ts, text = ts_text
            else:
                ts, text = datetime.now().strftime("%H:%M:%S"), ts_text
            if kind == "cr":
                if log_lines:
                    log_lines[-1] = text
                else:
                    log_lines.append(text)
            else:
                log_lines.append(f"[{ts}] {text}")
            dirty = True
        if len(log_lines) > 600:
            del log_lines[:-400]
            dirty = True
        if dirty:
            _set_log_text("\n".join(log_lines))
        for task in ui_tasks:
            try:
                task()
            except Exception:
                traceback.print_exc()

    def run_on_ui(fn):
        LOG_Q.put(("ui", fn))

    def flush():
        items = []
        try:
            while True:
                items.append(LOG_Q.get_nowait())
        except queue.Empty:
            pass
        if state["busy"]:
            el = int(time.time() - state["t0"])
            current = f"{state['name']} · {el}s"
            if op_text.cget("text") != current:
                op_text.configure(text=current)
        elif op_text.cget("text"):
            op_text.configure(text="")
        if items:
            apply_log_items(items)
        win.after(100, flush)

    lockables = []

    def _set_enabled(w, on):
        try:
            w.configure(state="normal" if on else "disabled")
        except Exception:
            pass

    autostart_switch_ref = {}

    def refresh_status():
        checks = [
            ("Python", find_python() is not None),
            ("venv", VENV_PY.exists()),
            ("Автозапуск", autostart_enabled()),
        ]
        for (label, ok), chip in zip(checks, chip_refs):
            chip["dot"].configure(text_color=OK if ok else "#565d68")
            chip["label"].configure(text=label)
        sw = autostart_switch_ref.get("sw")
        if sw is not None:
            if autostart_enabled():
                sw.select()
            else:
                sw.deselect()

    def job(name: str, fn, show_progress: bool = True):
        def wrapper(e=None):
            if state["busy"]:
                return
            state.update(busy=True, name=name, t0=time.time())
            op_text.configure(text=f"{name}...")
            for c in lockables:
                _set_enabled(c, False)
            ui_log(f"{'=' * 22}{name}{'=' * 22}")
            if show_progress:
                def reveal():
                    if state["busy"]:
                        show_progress_bar()
                win.after(800, reveal)

            def runner():
                ok = True
                try:
                    fn()
                except Exception as ex:
                    ok = False
                    ui_log(f"[ERROR] {ex}")
                finally:
                    def _finish():
                        hide_progress_bar()
                        state.update(busy=False, name=None)
                        op_text.configure(text="")
                        for c in lockables:
                            _set_enabled(c, True)
                        refresh_status()

                    run_on_ui(_finish)
                    ui_log(f"{'=' * 22}End {name}{' (FAILED)' if not ok else ''}{'=' * 22}")

            threading.Thread(target=runner, daemon=True).start()

        return wrapper

    def act_install():
        py = find_python()
        if not py:
            ui_log("Python 3 not found. Install Python 3.11+ from python.org (Add to PATH).")
            return
        fetch_and_copy()

    def act_models():
        if not VENV_PY.exists():
            raise RuntimeError("Install venv first.")
        rc = stream_process([str(VENV_PY), str(MODELS_SCRIPT)])
        if rc != 0:
            print("Models download failed - check your internet connection and try again.")

    def copy_all(e=None):
        try:
            win.clipboard_clear()
            win.clipboard_append("\n".join(log_lines))
            ui_log(f"Copied {len(log_lines)} lines to clipboard.")
        except Exception as ex:
            ui_log(f"[ERROR] clipboard: {ex}")

    def _clear_log(e=None):
        log_lines.clear()
        _set_log_text("")

    def ask_delete():
        if state["busy"]:
            return
        dlg = ctk.CTkToplevel(win)
        dlg.title("Удалить FriDay полностью")
        dlg.configure(fg_color=SURFACE2)
        dlg.resizable(False, False)
        dlg.transient(win)
        dlg.grab_set()
        ctk.CTkLabel(
            dlg, text="Удалить FriDay полностью?",
            font=F(16, "bold"), text_color=TXT,
        ).pack(pady=(28, 8))
        ctk.CTkLabel(
            dlg, text="Будут удалены: папка проекта, автозапуск и кэши моделей.",
            font=F(13), text_color=SUB, wraplength=380, justify="center",
        ).pack(padx=30)
        bar = ctk.CTkFrame(dlg, fg_color="transparent")
        bar.pack(pady=(24, 20))
        ctk.CTkButton(
            bar, text="Отмена", fg_color=SURFACE, hover_color="#2e333f",
            text_color=TXT, corner_radius=8, width=120, height=40,
            font=F(13), command=dlg.destroy,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            bar, text="Удалить всё", fg_color=DANGER, hover_color="#ca5652",
            text_color="#ffffff", corner_radius=8, width=120, height=40,
            font=F(13),
            command=lambda: (dlg.destroy(), job("Uninstall", lambda: initiate_full_delete(win), False)()),
        ).pack(side="left", padx=6)
        dlg.update_idletasks()
        dlg.geometry(
            f"440x190+{win.winfo_x() + (win.winfo_width() - 440) // 2}"
            f"+{win.winfo_y() + (win.winfo_height() - 190) // 2}"
        )

    # ─── Вкладка «Установка» ────────────────────────────────────────────────

    pad = 20
    installer_win.grid_columnconfigure(0, weight=1)
    installer_win.grid_rowconfigure(4, weight=1)

    header = ctk.CTkFrame(installer_win, fg_color="transparent")
    header.grid(row=0, column=0, sticky="ew", padx=pad, pady=(22, 0))

    ctk.CTkLabel(
        header, text=APP_NAME,
        font=F(20, "bold"), text_color=TXT,
    ).pack(side="left", padx=(0, 16))

    chip_refs = []
    for label in ("Python", "venv", "Автозапуск"):
        chip = ctk.CTkFrame(header, fg_color=SURFACE2, corner_radius=16)
        dot = ctk.CTkLabel(chip, text="●", font=F(11), text_color="#565d68")
        lbl = ctk.CTkLabel(chip, text=label, font=F(12), text_color=SUB)
        dot.pack(side="left", padx=(12, 4), pady=(7, 7))
        lbl.pack(side="left", padx=(4, 12), pady=(7, 7))
        chip.pack(side="left", padx=(0, 9))
        chip_refs.append({"dot": dot, "label": lbl})

    actions = ctk.CTkFrame(installer_win, fg_color="transparent")
    actions.grid(row=1, column=0, sticky="ew", padx=pad, pady=(20, 0))
    for i in range(6):
        actions.grid_columnconfigure(i, weight=1)

    progress_row = ctk.CTkFrame(installer_win, fg_color="transparent")
    progress_row.grid(row=2, column=0, sticky="ew", padx=pad, pady=(14, 0))
    progress = ctk.CTkProgressBar(
        progress_row, mode="indeterminate",
        progress_color=ACCENT, fg_color=SURFACE2, height=6,
        indeterminate_speed=0.5,
    )

    def show_progress_bar():
        progress.pack(fill="x")
        progress.start()

    def hide_progress_bar():
        progress.stop()
        progress.pack_forget()

    out_header = ctk.CTkFrame(installer_win, fg_color="transparent")
    out_header.grid(row=3, column=0, sticky="ew", padx=pad, pady=(14, 0))

    ctk.CTkLabel(
        out_header, text="ВЫВОД",
        font=F(11, "bold"), text_color=SUB,
    ).pack(side="left", padx=(2, 14))

    btn_clear = ctk.CTkButton(
        out_header, text="Очистить", width=96, height=28, corner_radius=6,
        fg_color=SURFACE2, hover_color="#2e333f", text_color=SUB,
        font=F(12), command=_clear_log,
    )
    btn_copy = ctk.CTkButton(
        out_header, text="Копировать", width=112, height=28, corner_radius=6,
        fg_color=SURFACE2, hover_color="#2e333f", text_color=SUB,
        font=F(12), command=copy_all,
    )
    op_text = ctk.CTkLabel(out_header, text="", font=F(12), text_color=SUB)
    btn_clear.pack(side="right")
    btn_copy.pack(side="right", padx=(0, 8))
    op_text.pack(side="right", padx=(0, 8))

    log_box.grid(row=4, column=0, sticky="nsew", padx=pad, pady=(10, 22))

    def make_btn(parent, text, fg, hover, tc, command, **kw):
        kw.setdefault("corner_radius", 8)
        kw.setdefault("height", 48)
        kw.setdefault("font", F(15))
        return ctk.CTkButton(
            parent, text=text, fg_color=fg, hover_color=hover,
            text_color=tc, command=command, **kw,
        )

    btn_install = make_btn(actions, "Установить", ACCENT, "#8fb4ff", "#0f1319",
                           job("Install", act_install))
    btn_update = make_btn(actions, "Обновить", SURFACE2, "#2e333f", TXT,
                          job("Update", act_install))
    btn_venv = make_btn(actions, "Зависимости", SURFACE2, "#2e333f", TXT,
                        job("Install venv", do_install_venv))
    btn_models = make_btn(actions, "Модели", SURFACE2, "#2e333f", TXT,
                          job("Download models", act_models))
    btn_run = make_btn(actions, "Запустить", SURFACE2, "#2e333f", TXT,
                       job("Run", run_friday, False))
    btn_delete = make_btn(
        actions, "Удалить", "#1c1f27", "#262a33", DANGER, ask_delete,
        border_width=1, border_color="#7a4543",
    )
    row_buttons = [btn_install, btn_update, btn_venv, btn_models, btn_run, btn_delete]
    for i, b in enumerate(row_buttons):
        b.grid(
            row=0, column=i, sticky="nsew",
            padx=(0 if i == 0 else 5, 5 if i < len(row_buttons) - 1 else 0),
        )
    lockables.extend(row_buttons + [btn_copy, btn_clear])

    # ─── Вкладка «Настройки» ────────────────────────────────────────────────

    settings_win.grid_columnconfigure(0, weight=1)
    settings_win.grid_rowconfigure(1, weight=1)

    top = ctk.CTkFrame(settings_win, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(22, 14))

    settings_note = ctk.CTkLabel(top, text="", font=F(12), text_color=OK)
    settings_note.pack(side="left", fill="x", expand=True, padx=(2, 8))

    btn_reload = ctk.CTkButton(
        top, text="Сбросить", fg_color=SURFACE2, hover_color="#2e333f",
        text_color=TXT, corner_radius=8, height=40, font=F(13),
    )
    btn_reload.pack(side="right")
    btn_save = ctk.CTkButton(
        top, text="Сохранить", fg_color=ACCENT, hover_color="#8fb4ff",
        text_color="#0f1319", corner_radius=8, height=40, font=F(13),
    )
    btn_save.pack(side="right", padx=(8, 0))

    scroll = ctk.CTkScrollableFrame(settings_win, fg_color=BG)
    scroll.grid(row=1, column=0, sticky="nsew", padx=pad, pady=(0, 22))

    kinds_map = {}
    for _t, rows in CONFIG_SECTIONS:
        for sec, key, _lbl, kind in rows:
            kinds_map[(sec, key)] = kind

    initial_values = load_config_values()
    settings_fields = {}

    def _build_section_card(title, rows):
        sec_card = ctk.CTkFrame(
            scroll, fg_color=SURFACE, corner_radius=10,
            border_width=1, border_color=BORDER,
        )
        sec_card.pack(fill="x", pady=6)
        ctk.CTkLabel(
            sec_card, text=title.upper(),
            font=F(12, "bold"), text_color="#98a2b0",
        ).pack(anchor="w", padx=18, pady=(15, 6))

        pairs = [rows[i:i + 2] for i in range(0, len(rows), 2)]
        for pair in pairs:
            rframe = ctk.CTkFrame(sec_card, fg_color="transparent")
            rframe.pack(fill="x", padx=14, pady=3)
            rframe.grid_columnconfigure(0, weight=1)
            if len(pair) == 2:
                rframe.grid_columnconfigure(1, weight=1)
            for col, (sec, key, label, _kind) in enumerate(pair):
                cell = ctk.CTkFrame(rframe, fg_color="transparent")
                cell.grid(row=0, column=col, sticky="nsew",
                          padx=(6 if col == 0 else 3, 3 if col == 0 else 6))
                ctk.CTkLabel(
                    cell, text=label,
                    font=F(12), text_color=LABEL,
                ).pack(anchor="w", padx=(4, 4))
                entry = ctk.CTkEntry(
                    cell, fg_color=SURFACE2, border_color=BORDER, border_width=1,
                    corner_radius=8, text_color=TXT,
                    font=F(14), height=46,
                )
                entry.pack(fill="x", pady=(6, 4), padx=(4, 4))
                v = initial_values.get((sec, key))
                if v is not None:
                    entry.insert(0, str(v))
                settings_fields[(sec, key)] = entry

    top_sections = ("Weather", "Music")
    for title, rows in CONFIG_SECTIONS:
        if title in top_sections:
            _build_section_card(title, rows)

    autostart_card = ctk.CTkFrame(
        scroll, fg_color=SURFACE, corner_radius=10,
        border_width=1, border_color=BORDER,
    )
    autostart_card.pack(fill="x", pady=(2, 2))
    card_left = ctk.CTkFrame(autostart_card, fg_color="transparent")
    card_left.pack(side="left", fill="both", expand=True, padx=18, pady=14)
    ctk.CTkLabel(
        card_left, text="Автозапуск",
        font=F(14, "bold"), text_color=TXT,
    ).pack(anchor="w")
    ctk.CTkLabel(
        card_left, text="Запускать FriDay при входе в Windows",
        font=F(12), text_color=LABEL,
    ).pack(anchor="w")
    autostart_switch = ctk.CTkSwitch(
        autostart_card, text="", progress_color=ACCENT, button_color=ACCENT,
    )
    autostart_switch.pack(side="right", padx=(0, 20))
    if autostart_enabled():
        autostart_switch.select()
    autostart_switch.configure(
        command=lambda: job("Toggle autostart", toggle_autostart, False)()
    )
    autostart_switch_ref["sw"] = autostart_switch

    for title, rows in CONFIG_SECTIONS:
        if title not in top_sections:
            _build_section_card(title, rows)

    def _file_has_unknown_keys() -> bool:
        try:
            import yaml

            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            return True
        known = set(kinds_map.keys())
        sections = {sec for sec, _k in known if sec}
        for k, v in data.items():
            if isinstance(v, dict):
                if k not in sections:
                    return True
                for kk in v:
                    if (k, kk) not in known:
                        return True
            else:
                if (None, k) not in known:
                    return True
        return False

    def act_save_settings(e=None):
        errors = []
        parsed = {}
        for (sec, key), entry in settings_fields.items():
            kind = kinds_map[(sec, key)]
            raw = (entry.get() or "").strip()
            try:
                parsed[(sec, key)] = _format_yaml_value(kind, raw)
            except Exception:
                errors.append(f"{key}: '{raw}'")
        if errors:
            settings_note.configure(text="Ошибка: " + "; ".join(errors), text_color=DANGER)
            return
        defaults = _defaults_from_template()
        is_default = all(parsed.get(k) == v for k, v in defaults.items())
        if is_default and not CONFIG_PATH.exists():
            settings_note.configure(text="Всё стандартно — файл не требуется", text_color=OK)
            ui_log("Config equals defaults: files/config.yml not created.")
            return
        try:
            save_config_values(parsed)
            if is_default and CONFIG_PATH.exists() and not _file_has_unknown_keys():
                CONFIG_PATH.unlink()
                settings_note.configure(text="Значения стандартные — config.yml удалён", text_color=OK)
                ui_log("Config equals defaults: files/config.yml removed. Restart FriDay to apply.")
                return
        except Exception as ex:
            settings_note.configure(text=f"Не сохранено: {ex}", text_color=DANGER)
            return
        settings_note.configure(text="Сохранено — перезапустите FriDay", text_color=OK)
        ui_log("files/config.yml saved. Restart FriDay to apply changes.")

    def reload_settings(e=None):
        values = load_config_values()
        for (sec, key), v in values.items():
            entry = settings_fields.get((sec, key))
            if entry is not None:
                entry.delete(0, "end")
                if v is not None:
                    entry.insert(0, str(v))
        settings_note.configure(text="")

    btn_save.configure(command=act_save_settings)
    btn_reload.configure(command=reload_settings)

    lockables.extend([btn_save, btn_reload, autostart_switch])

    # ─── Вкладка «Пресеты» ───────────────────────────────────────────────────

    PRESET_PATH = BASE_DIR / "files" / "presets.json"

    def preset_read():
        if not PRESET_PATH.exists():
            return []
        try:
            data = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def preset_write(presets):
        PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
        PRESET_PATH.write_text(
            json.dumps(presets, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def preset_names():
        return [p["name"] for p in preset_read() if isinstance(p, dict) and p.get("name")]

    def preset_get(name):
        for p in preset_read():
            if isinstance(p, dict) and p.get("name") == name:
                return p
        return None

    def preset_add(name, apps):
        data = preset_read()
        data.append({"name": name, "apps": list(apps)})
        preset_write(data)

    def preset_update(old_name, new_name, apps):
        data = preset_read()
        for p in data:
            if isinstance(p, dict) and p.get("name") == old_name:
                p["name"] = new_name
                p["apps"] = list(apps)
                break
        preset_write(data)

    def preset_delete(name):
        preset_write([
            p for p in preset_read()
            if not (isinstance(p, dict) and p.get("name") == name)
        ])

    from tkinter import filedialog, messagebox

    presets_win.grid_rowconfigure(0, weight=1)
    presets_win.grid_columnconfigure(1, weight=1)

    side = ctk.CTkFrame(presets_win, fg_color="transparent")
    side.grid(row=0, column=0, sticky="nsew", padx=(pad, 5), pady=pad)
    side.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        side, text="Пресеты", font=F(16, "bold"), text_color=TXT,
    ).pack(anchor="w", padx=4, pady=(0, 8))

    list_box = ctk.CTkScrollableFrame(side, fg_color=SURFACE, corner_radius=10, width=210)
    list_box.pack(fill="both", expand=True)
    list_box.grid_columnconfigure(0, weight=1)

    btn_new = ctk.CTkButton(
        side, text="+ Новый пресет", fg_color=ACCENT, hover_color="#8fb4ff",
        text_color="#0f1319", corner_radius=8, height=36, font=F(13, "bold"),
    )
    btn_new.pack(fill="x", pady=(10, 0))

    editor = ctk.CTkFrame(
        presets_win, fg_color=SURFACE, corner_radius=10,
        border_width=1, border_color=BORDER,
    )
    editor.grid(row=0, column=1, sticky="nsew", padx=(5, pad), pady=pad)
    editor.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        editor, text="Редактор пресета", font=F(15, "bold"), text_color=TXT,
    ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))

    name_frame = ctk.CTkFrame(editor, fg_color="transparent")
    name_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 8))
    name_frame.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(
        name_frame, text="Имя:", font=F(13), text_color=LABEL,
    ).grid(row=0, column=0, sticky="w", padx=(0, 8))
    name_entry = ctk.CTkEntry(
        name_frame, fg_color=SURFACE2, border_color=BORDER,
        text_color=TXT, font=F(13), height=36, corner_radius=8,
    )
    name_entry.grid(row=0, column=1, sticky="ew")

    ctk.CTkLabel(
        editor, text="Программы:", font=F(13), text_color=LABEL,
    ).grid(row=2, column=0, sticky="nw", padx=16, pady=(2, 4))

    apps_box = ctk.CTkScrollableFrame(editor, fg_color=SURFACE2, corner_radius=8)
    apps_box.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 4))
    apps_box.grid_columnconfigure(0, weight=1)
    editor.grid_rowconfigure(3, weight=1)

    _preset_selected = [""]
    _preset_btns = {}
    _app_rows = []

    def preset_app_paths():
        paths = []
        for w in _app_rows:
            child = w.winfo_children()[0]
            if isinstance(child, ctk.CTkLabel):
                paths.append(child.cget("text"))
        return paths

    def preset_render_apps(paths):
        for w in _app_rows:
            w.destroy()
        _app_rows.clear()
        for path in paths:
            row = ctk.CTkFrame(apps_box, fg_color="#2b303c", corner_radius=6)
            row.pack(fill="x", pady=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                row, text=path, font=F(12), text_color=LABEL, anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=6)
            ctk.CTkButton(
                row, text="X", width=30, height=26, corner_radius=6,
                fg_color=DANGER, hover_color="#8a3a36", text_color="#ffffff",
                font=F(12, "bold"),
                command=lambda p=path: preset_render_apps(
                    [x for x in preset_app_paths() if x != p]
                ),
            ).grid(row=0, column=1, padx=(4, 6))
            _app_rows.append(row)

    def preset_add_files():
        files = filedialog.askopenfilenames(title="Выберите программы или файлы")
        if not files:
            return
        existing = preset_app_paths()
        for f in files:
            if f not in existing:
                existing.append(f)
        preset_render_apps(existing)

    def preset_clear_details():
        name_entry.delete(0, "end")
        preset_render_apps([])

    def preset_show_details(name):
        p = preset_get(name)
        if p is None:
            return
        name_entry.delete(0, "end")
        name_entry.insert(0, str(p.get("name", "")))
        preset_render_apps(p.get("apps", []))

    def preset_select(name):
        _preset_selected[0] = name
        for n, btn in _preset_btns.items():
            if n == name:
                btn.configure(fg_color=ACCENT, text_color="#0f1319")
            else:
                btn.configure(fg_color=SURFACE2, text_color=LABEL)
        preset_show_details(name)

    def preset_refresh_list(select_name=None):
        for w in list_box.winfo_children():
            w.destroy()
        _preset_btns.clear()
        names = preset_names()
        if not names:
            ctk.CTkLabel(
                list_box, text="Нет пресетов", font=F(12), text_color=SUB,
            ).pack(pady=18)
            preset_clear_details()
            return
        for name in names:
            btn = ctk.CTkButton(
                list_box, text=name, anchor="w", height=32, corner_radius=8,
                fg_color=SURFACE2, hover_color="#2e333f", text_color=LABEL,
                font=F(12), command=lambda n=name: preset_select(n),
            )
            btn.pack(fill="x", padx=4, pady=2)
            _preset_btns[name] = btn
        if select_name:
            preset_select(select_name)
        else:
            preset_select(names[0])

    def preset_save():
        name = name_entry.get().strip()
        paths = preset_app_paths()
        old_name = _preset_selected[0]
        if not name:
            messagebox.showwarning("Ошибка", "Введите имя пресета")
            return
        if not paths:
            messagebox.showwarning("Ошибка", "Добавьте хотя бы одну программу")
            return
        if old_name:
            preset_update(old_name, name, paths)
            _preset_btns.pop(old_name, None)
            _preset_selected[0] = name
            ui_log(f"Preset updated: {name}")
        else:
            if preset_get(name):
                messagebox.showwarning("Ошибка", "Пресет с таким именем уже существует")
                return
            preset_add(name, paths)
            _preset_selected[0] = name
            ui_log(f"Preset saved: {name}")
        preset_refresh_list(select_name=name)

    def preset_delete_current():
        name = _preset_selected[0]
        if not name:
            return
        if not messagebox.askyesno("Подтверждение", f'Удалить пресет "{name}"?'):
            return
        preset_delete(name)
        _preset_btns.pop(name, None)
        remaining = preset_names()
        ui_log(f"Preset deleted: {name}")
        preset_refresh_list(select_name=remaining[0] if remaining else None)

    def preset_create_new():
        _preset_selected[0] = ""
        for b in _preset_btns.values():
            b.configure(fg_color=SURFACE2, text_color=LABEL)
        preset_clear_details()
        name_entry.focus_set()

    btn_new.configure(command=preset_create_new)

    btn_row = ctk.CTkFrame(editor, fg_color="transparent")
    btn_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 14))
    btn_row.grid_columnconfigure(2, weight=1)

    ctk.CTkButton(
        btn_row, text="+ Добавить файл", corner_radius=8, height=34,
        fg_color=SURFACE2, hover_color="#2e333f", text_color=TXT,
        font=F(12), command=preset_add_files,
    ).grid(row=0, column=0, padx=(0, 6))

    ctk.CTkButton(
        btn_row, text="Сохранить", corner_radius=8, height=34,
        fg_color=ACCENT, hover_color="#8fb4ff", text_color="#0f1319",
        font=F(12, "bold"), command=preset_save,
    ).grid(row=0, column=1, padx=6)

    ctk.CTkButton(
        btn_row, text="Удалить", corner_radius=8, height=34,
        fg_color="#1c1f27", hover_color="#262a33", text_color=DANGER,
        border_width=1, border_color="#7a4543",
        font=F(12, "bold"), command=preset_delete_current,
    ).grid(row=0, column=2, padx=6, sticky="e")

    preset_refresh_list()

    if os.environ.get("FRIDAY_INSTALLER_PROFILE"):
        t_ui = time.monotonic()
        win.geometry("960x700+-3200-3200")
        profile_path = Path(tempfile.gettempdir()) / "friday_profile.txt"
        prof = {"t_paint": None}

        def _dump_profile():
            ts = time.monotonic()
            p = prof["t_paint"]
            lines = [
                f"module_imports {t_ctk - _T0:.3f}s",
                f"tk_window {t_win - _T0:.3f}s",
                f"ui_built {t_ui - _T0:.3f}s",
                f"first_paint {p - _T0:.3f}s" if p else "first_paint n/a",
                f"up_to_destroy {ts - _T0:.3f}s",
            ]
            try:
                profile_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception:
                pass
            win.destroy()

        win.after(1500, _dump_profile)

    win.after(120, refresh_status)
    win.after(100, flush)
    win.update_idletasks()
    win.update()
    if os.environ.get("FRIDAY_INSTALLER_PROFILE"):
        prof["t_paint"] = time.monotonic()
    win.mainloop()


def main() -> None:
    # Ставим роутер вывода до всего остального: в сборке --noconsole
    # sys.stdout/sys.stderr равны None, и первый же print() уронил бы
    # установщик (в том числе тихий режим --cleanup). После этого print()
    # попадает в лог-панель GUI (или в консоль при запуске из исходников).
    install_output_router()
    if len(sys.argv) >= 3 and sys.argv[1] == "--cleanup":
        cleanup_mode(sys.argv[2])
        return
    try:
        build_ui()
    except SystemExit:
        raise
    except Exception:
        err = traceback.format_exc()
        try:
            with open(Path(__file__).with_name("error.log"), "w", encoding="utf-8") as f:
                f.write(err)
        except Exception:
            pass
        os._exit(1)
    finally:
        remove_bundled_font()


if __name__ == "__main__":
    main()


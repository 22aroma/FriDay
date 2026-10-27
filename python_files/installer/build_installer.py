import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent.parent
DIST_DIR = HERE / "dist"
APP_DIR = DIST_DIR / "FriDay"
ARCHIVE = ROOT_DIR / "FriDay.zip"

# Лицензионные файлы кладём в архив, сохраняя раскладку репозитория: в exe
# встроен шрифт Martian Mono (OFL требует сопровождать его текстом лицензии),
# а вместе с программой должны распространяться MIT и уведомления о компонентах.
LICENSE_FILES = (
    (ROOT_DIR / "LICENSE", Path("LICENSE")),
    (ROOT_DIR / "THIRD_PARTY_NOTICES.md", Path("THIRD_PARTY_NOTICES.md")),
    (ROOT_DIR / "files" / "fonts" / "OFL.txt", Path("files/fonts/OFL.txt")),
)

BUILD_PY = Path(os.environ.get("FRIDAY_BUILD_PYTHON", sys.executable))


def run(cmd, **kw):
    print("> " + " ".join(str(c) for c in cmd))
    return subprocess.call([str(c) for c in cmd], cwd=HERE, **kw)


def clean_artifacts():
    for leftover in ("build", "FriDay.spec", "__pycache__"):
        p = HERE / leftover
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    if DIST_DIR.is_dir():
        shutil.rmtree(DIST_DIR, ignore_errors=True)


def copy_licenses() -> bool:
    """Копируем LICENSE, THIRD_PARTY_NOTICES и OFL шрифта в папку сборки.

    Пути повторяют раскладку репозитория, чтобы после установки (проект
    скачивается с GitHub) файлы не размножались по разным каталогам.
    """
    missing = [str(src) for src, _rel in LICENSE_FILES if not src.exists()]
    if missing:
        print("License files not found: " + ", ".join(missing))
        return False
    for src, rel in LICENSE_FILES:
        dst = APP_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print("Licenses -> " + ", ".join(rel.as_posix() for _src, rel in LICENSE_FILES))
    return True


def make_archive() -> None:
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    print(f"Zipping {APP_DIR} -> {ARCHIVE}")
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for item in sorted(APP_DIR.rglob("*")):
            if item.is_file():
                z.write(item, item.relative_to(DIST_DIR))


def main() -> int:
    root_exe = HERE.parent.parent / "FriDay.exe"
    if root_exe.exists():
        print(f"Removing old {root_exe}")
        root_exe.unlink()

    clean_artifacts()

    rc = run(
        [
            BUILD_PY,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--disable-pip-version-check",
            "pyinstaller",
            "requests",
            "pyyaml",
            "customtkinter==5.2.2",
        ]
    )
    if rc != 0:
        print("pip install failed")
        return 1

    icon = HERE.parent.parent / "files" / "icon.ico"
    font = HERE.parent.parent / "files" / "fonts" / "MartianMono.ttf"
    rc = run(
        [
            BUILD_PY,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--noconsole",
            "--name",
            "FriDay",
            "--icon",
            str(icon),
            "--add-data",
            f"{icon};.",
            "--add-data",
            f"{font};.",
            "--collect-all",
            "customtkinter",
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            "build",
            "--specpath",
            ".",
            "installer_app.py",
        ]
    )
    if rc != 0:
        print("BUILD FAILED")
        return 1

    if not (APP_DIR / "FriDay.exe").exists():
        print("BUILD FAILED: exe not found")
        return 1
    if not copy_licenses():
        print("BUILD FAILED: licenses missing")
        return 1

    for leftover in ("build", "FriDay.spec", "__pycache__"):
        p = HERE / leftover
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()

    make_archive()
    shutil.rmtree(DIST_DIR, ignore_errors=True)

    print()
    print(f"Done: {ARCHIVE}")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("Press Enter to exit...")
    except EOFError:
        pass
    sys.exit(code)
import os
import sys
import urllib.request

# Xet может падать "File reconstruction error" на нестабильной сети — используем
# обычные HTTP-загрузки с докачкой. Должен стоять до импорта huggingface_hub.
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')

import torch
from huggingface_hub import hf_hub_download


def check_connectivity() -> bool:
    for url in [
        "https://huggingface.co",
        "https://cdn-lfs.huggingface.co",
        "https://github.com",
    ]:
        try:
            urllib.request.urlopen(url, timeout=10)
            return True
        except Exception:
            continue
    return False


def download_silero_vad():
    print("  Silero VAD (ONNX)...")
    torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        onnx=True,
        force_onnx_cpu=True,
        force_reload=False,
        trust_repo=True,
        skip_validation=True,
    )
    print("    OK")


def download_silero_tts():
    print("  Silero TTS...")
    torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker="v5_4_ru",
        trust_repo=True,
        skip_validation=True,
    )
    print("    OK")


def download_transcribe_asr() -> bool:
    print("  Transcribe ASR (GigaAM-v3 GGUF Q8_0)...")
    repo_id = "handy-computer/gigaam-v3-e2e-rnnt-gguf"
    filename = "gigaam-v3-e2e-rnnt-Q8_0.gguf"
    sys.stdout.write(f"    {filename}... ")
    sys.stdout.flush()
    try:
        hf_hub_download(repo_id=repo_id, filename=filename)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED ({e})")
        return False


def main() -> int:
    asr_only = "--asr-only" in sys.argv
    print("")
    print("=== Downloading models ===")
    print("")

    if not check_connectivity():
        print("Не удалось подключиться к серверам загрузки (Hugging Face / GitHub).")
        print("Проверьте подключение к интернету и повторите запуск.")
        return 1

    ok = True
    if not asr_only:
        for title, step in (
            ("Silero VAD", download_silero_vad),
            ("Silero TTS", download_silero_tts),
        ):
            try:
                step()
            except Exception as e:
                print(f"  Ошибка загрузки {title}: {e}")
                ok = False

    if not download_transcribe_asr():
        ok = False

    print("")
    print("Done." if ok else "Загрузка завершена с ошибками.")
    print("")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

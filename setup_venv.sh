#!/bin/bash
# Оптимизированная установка для Arch Linux
set -e

echo "=== Создание оптимизированного venv ==="

# Удаляем старое окружение
rm -rf venv

# Создаем новое
python3 -m venv venv
source venv/bin/activate

# Обновляем pip
pip install --upgrade pip

# Устанавливаем все пакеты обычным способом (кроме torch)
pip install num2words==0.5.14 numpy==2.4.4 packaging==26.2 pillow==12.2.0
pip install PyAudio==0.2.14 pystray==0.19.5 requests==2.33.1
pip install sounddevice==0.5.5 omegaconf==2.3.0
pip install ddgs==9.14.4 kairos-asr==0.7.0 onnxruntime

# Устанавливаем torch CPU-only версию
pip install --index-url https://download.pytorch.org/whl/cpu torch==2.11.0+cpu torchaudio==2.11.0+cpu

# Оптимизация: агрессивная очистка torch
echo "=== Очистка torch от лишнего ==="
TORCH_DIR="venv/lib/python3.14/site-packages/torch"

# Тестовые данные и бинарники
rm -rf "$TORCH_DIR/test"
rm -rf "$TORCH_DIR/include"
find "$TORCH_DIR/bin" -type f ! -name "torch_shm_manager" -delete 2>/dev/null || true

# Неиспользуемые модули
rm -rf "$TORCH_DIR/onnx"
rm -rf "$TORCH_DIR/_inductor"
rm -rf "$TORCH_DIR/_dynamo"
rm -f "$TORCH_DIR/lib/libjitbackend_test.so"
rm -f "$TORCH_DIR/lib/libtorchbind_test.so"
rm -f "$TORCH_DIR/lib/libaoti_custom_ops.so"

# Очистка по всем пакетам
find venv/lib/python3.14/site-packages -name "*.so" -type f -exec strip --strip-debug {} \; 2>/dev/null || true
find venv/lib/python3.14/site-packages -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find venv -name "*.pyc" -delete 2>/dev/null || true
find venv/lib/python3.14/site-packages -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find venv/lib/python3.14/site-packages -type d -name "examples" -exec rm -rf {} + 2>/dev/null || true
find venv/lib/python3.14/site-packages -name "*.c" -delete 2>/dev/null || true
find venv/lib/python3.14/site-packages -name "*.pxd" -delete 2>/dev/null || true
rm -rf venv/share 2>/dev/null || true

# Удаляем pip/setuptools (не нужны в runtime)
rm -rf venv/lib/python3.14/site-packages/pip*
rm -rf venv/lib/python3.14/site-packages/setuptools*
rm -rf venv/lib/python3.14/site-packages/_distutils*
rm -rf venv/lib/python3.14/site-packages/pkg_resources*
rm -f venv/lib/python3.14/site-packages/distutils-precedence.pth

# Очистка кэша
pip cache purge 2>/dev/null || true
rm -rf ~/.cache/pip 2>/dev/null || true

# Показываем итоговый размер
echo ""
echo "=== Итоговый размер ==="
du -sh venv/
echo "--- torch ---"
du -sh "$TORCH_DIR/"
echo ""
echo "Готово! Venv оптимизирован (~680MB вместо 1.2GB)"

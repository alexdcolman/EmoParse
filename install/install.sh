#!/usr/bin/env bash
set -e

echo "Installing system dependencies..."
sudo apt update
sudo apt install -y \
    build-essential \
    git \
    curl \
    cmake \
    python3-venv \
    python3-dev \
    libopenblas-dev \
    libomp-dev \
    chromium-browser \
    chromium-chromedriver

echo
echo "Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

echo
echo "Installing Python dependencies..."
# Excluimos llama_cpp_python — requiere flags CUDA y se instala al final
grep -v 'llama_cpp_python' requirements.txt > /tmp/requirements_no_llama.txt
pip install -r /tmp/requirements_no_llama.txt

echo
echo "Checking GPU..."
python install/check_gpu.py

echo
echo "Detecting recommended model..."
python install/recommend_models.py

echo
echo "Installing llama_cpp_python with CUDA support..."
CUDACXX=/usr/local/cuda/bin/nvcc \
CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=all-major" \
pip install llama_cpp_python==0.3.16 --no-cache-dir

# echo
# echo "Downloading models..."
# python install/download_models.py

echo
echo "Configuring runtime..."
python install/configure_runtime.py

echo
echo "Installation complete."
echo
echo "Run with:"
echo
echo "    source .venv/bin/activate"
echo "    python run.py"

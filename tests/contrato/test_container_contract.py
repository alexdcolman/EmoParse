from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cpu_container_profile_is_local_api_and_dashboard_ready() -> None:
    text = _read("docker/Dockerfile.cpu")
    assert "FROM python:3.12-slim-bookworm" in text
    assert '".[ui,lmstudio]"' in text
    assert "STREAMLIT_SERVER_ADDRESS=0.0.0.0" in text
    assert 'ENTRYPOINT ["emoparse"]' in text
    assert "COPY . ." not in text


def test_cuda_container_profile_builds_llama_cpp_with_cuda() -> None:
    text = _read("docker/Dockerfile.cuda")
    assert "nvidia/cuda:${CUDA_VERSION}-devel-${CUDA_DISTRO}" in text
    assert "nvidia/cuda:${CUDA_VERSION}-runtime-${CUDA_DISTRO}" in text
    assert "CMAKE_ARGS=-DGGML_CUDA=on" in text
    assert '".[llamacpp,ui,lmstudio]"' in text
    assert 'metadata.distribution("llama-cpp-python")' in text
    assert "libggml-cuda.so" in text
    assert "import llama_cpp" not in text
    assert "COPY . ." not in text


def test_cuda_runtime_uses_numeric_identity_without_creating_named_user_or_group() -> None:
    text = _read("docker/Dockerfile.cuda")
    assert "groupadd" not in text
    assert "useradd" not in text
    assert "ENV HOME=/home/emoparse" in text
    assert "USER ${EMOPARSE_UID}:${EMOPARSE_GID}" in text
    assert "/home/emoparse /models /data /runs /config" in text


def test_container_context_excludes_local_state_and_models() -> None:
    ignored = {line.strip() for line in _read(".dockerignore").splitlines() if line.strip()}
    required = {
        ".git",
        ".github",
        ".assistant",
        ".dev",
        ".venv",
        "models",
        "*.gguf",
        "runs",
        "exports",
        "logs",
        "data",
        "evals",
        "tutorial",
        "docs",
        "tests",
        "_prueba",
    }
    assert required <= ignored


def test_container_smoke_cli_exposes_both_profiles() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/container_smoke.py", "--help"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "--profile {cpu,cuda}" in result.stdout
    assert "--no-build" in result.stdout


def test_cuda_smokes_request_nvidia_runtime() -> None:
    namespace = runpy.run_path(
        str(ROOT / "scripts/container_smoke.py"), run_name="container_smoke_gpu_contract"
    )
    gpu_args = namespace["_docker_gpu_args"]
    imports_code = namespace["_imports_smoke_code"]

    assert gpu_args("cpu") == []
    assert gpu_args("cuda") == ["--gpus", "all"]
    cuda_imports = imports_code("cuda")
    assert "ctypes.CDLL('libcuda.so.1')" in cuda_imports
    assert "llama_supports_gpu_offload" in cuda_imports
    assert "llama_max_devices" in cuda_imports


def test_container_python_c_snippets_compile_before_docker() -> None:
    namespace = runpy.run_path(
        str(ROOT / "scripts/container_smoke.py"), run_name="container_smoke_contract"
    )

    imports_code = namespace["_imports_smoke_code"]
    mount_code = namespace["_mount_smoke_code"]
    dashboard_code = namespace["_dashboard_health_code"]

    compile(imports_code("cpu"), "<cpu-imports>", "exec")
    compile(imports_code("cuda"), "<cuda-imports>", "exec")
    mount_source = mount_code()
    compile(mount_source, "<mounts>", "exec")
    compile(dashboard_code(), "<dashboard>", "exec")

    # El contenido esperado conserva el newline como escape dentro del source
    # y no como salto físico capaz de cortar el literal de `python -c`.
    assert repr("pipeline: {}\n") in mount_source

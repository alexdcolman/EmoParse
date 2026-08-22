from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = {
    "cpu": ROOT / "docker" / "Dockerfile.cpu",
    "cuda": ROOT / "docker" / "Dockerfile.cuda",
}
DEFAULT_IMAGES = {"cpu": "emoparse:cpu", "cuda": "emoparse:cuda"}


def _run(
    command: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("docker no está disponible en PATH")
    _run(["docker", "version"], capture_output=True)


def _build(profile: str, image: str) -> None:
    dockerfile = DOCKERFILES[profile]
    _run(
        [
            "docker",
            "build",
            "--quiet",
            "--file",
            str(dockerfile),
            "--build-arg",
            f"EMOPARSE_UID={os.getuid()}",
            "--build-arg",
            f"EMOPARSE_GID={os.getgid()}",
            "--tag",
            image,
            str(ROOT),
        ]
    )


def _docker_gpu_args(profile: str) -> list[str]:
    return ["--gpus", "all"] if profile == "cuda" else []


def _smoke_cli(profile: str, image: str) -> None:
    _run(["docker", "run", "--rm", *_docker_gpu_args(profile), image, "--help"])


def _checked_python_code(code: str, label: str) -> str:
    # Todo fragmento que vaya a `python -c` se compila localmente antes de
    # cruzar el límite del subprocess/contenedor. Esto detecta comillas,
    # escapes y saltos de línea inválidos antes de invocar Docker.
    compile(code, label, "exec")
    return code


def _imports_smoke_code(profile: str) -> str:
    parts = [
        "import emoparse",
        "import openai",
        "import streamlit",
    ]
    if profile == "cuda":
        parts.extend(
            [
                "from pathlib import Path",
                "import ctypes",
                "ctypes.CDLL('libcuda.so.1')",
                "import llama_cpp",
                "libdir = Path(llama_cpp.__file__).resolve().parent / 'lib'",
                "assert any(libdir.glob('*cuda*')), libdir",
                "print('LLAMA_GPU_OFFLOAD=', llama_cpp.llama_supports_gpu_offload())",
                "print('LLAMA_MAX_DEVICES=', llama_cpp.llama_max_devices())",
            ]
        )
    parts.append("print('IMPORTS=OK')")
    return _checked_python_code("; ".join(parts), "<container-smoke-imports>")


def _mount_smoke_code() -> str:
    # repr() conserva el newline esperado como escape dentro del código fuente
    # entregado a `python -c`; nunca inserta un salto real dentro del literal.
    expected_config = repr("pipeline: {}\n")
    code = (
        "from pathlib import Path; import sqlite3; "
        "assert Path('/models/external-model.gguf').read_text() == 'external-model'; "
        "assert Path('/data/input.txt').read_text() == 'external-data'; "
        f"assert Path('/config/config.yaml').read_text() == {expected_config}; "
        "db = sqlite3.connect('/runs/smoke.sqlite'); "
        "db.execute('create table smoke (value text)'); "
        "db.execute(\"insert into smoke values ('ok')\"); "
        "db.commit(); "
        "assert db.execute('select value from smoke').fetchone()[0] == 'ok'; "
        "db.close(); print('MOUNTS_SQLITE=OK')"
    )
    return _checked_python_code(code, "<container-smoke-mounts>")


def _dashboard_health_code() -> str:
    code = (
        "import urllib.request; "
        "body = urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2).read(); "
        "assert body.strip() == b'ok', body; print('DASHBOARD=OK')"
    )
    return _checked_python_code(code, "<container-smoke-dashboard>")


def _smoke_imports(profile: str, image: str) -> None:
    _run(
        [
            "docker",
            "run",
            "--rm",
            *_docker_gpu_args(profile),
            "--entrypoint",
            "python",
            image,
            "-c",
            _imports_smoke_code(profile),
        ]
    )


def _smoke_mounts_and_sqlite(profile: str, image: str) -> None:
    with tempfile.TemporaryDirectory(prefix="emoparse_container_smoke_") as temp_dir:
        root = Path(temp_dir)
        models = root / "models"
        data = root / "data"
        runs = root / "runs"
        config = root / "config"
        for directory in (models, data, runs, config):
            directory.mkdir()
        (models / "external-model.gguf").write_text("external-model", encoding="utf-8")
        (data / "input.txt").write_text("external-data", encoding="utf-8")
        (config / "config.yaml").write_text("pipeline: {}\n", encoding="utf-8")

        code = _mount_smoke_code()
        _run(
            [
                "docker",
                "run",
                "--rm",
                *_docker_gpu_args(profile),
                "--entrypoint",
                "python",
                "--volume",
                f"{models}:/models:ro",
                "--volume",
                f"{data}:/data:ro",
                "--volume",
                f"{runs}:/runs",
                "--volume",
                f"{config}:/config:ro",
                image,
                "-c",
                code,
            ]
        )
        if not (runs / "smoke.sqlite").is_file():
            raise RuntimeError("el smoke no creó /runs/smoke.sqlite en el bind mount")


def _smoke_dashboard(profile: str, image: str) -> None:
    name = f"emoparse-smoke-{profile}-{os.getpid()}"
    started = _run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            *_docker_gpu_args(profile),
            image,
            "app",
            "--port",
            "8501",
            "--no-browser",
        ],
        capture_output=True,
    )
    container_id = started.stdout.strip()
    if not container_id:
        raise RuntimeError("docker run no devolvió id para el dashboard")

    health_code = _dashboard_health_code()
    try:
        for _ in range(45):
            probe = _run(
                ["docker", "exec", name, "python", "-c", health_code],
                check=False,
                capture_output=True,
            )
            if probe.returncode == 0:
                print(probe.stdout.strip(), flush=True)
                return
            time.sleep(1)
        logs = _run(["docker", "logs", name], check=False, capture_output=True)
        raise RuntimeError(f"dashboard sin health OK\n{logs.stdout}\n{logs.stderr}")
    finally:
        _run(["docker", "rm", "--force", name], check=False, capture_output=True)


def smoke(profile: str, image: str, *, build: bool) -> dict[str, object]:
    _require_docker()
    if build:
        _build(profile, image)
    _smoke_cli(profile, image)
    _smoke_imports(profile, image)
    _smoke_mounts_and_sqlite(profile, image)
    _smoke_dashboard(profile, image)
    result = {
        "status": "OK",
        "profile": profile,
        "image": image,
        "model_used": False,
        "smokes": ["cli", "imports", "mounts", "sqlite", "dashboard"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Construye y prueba los perfiles de contenedor CPU/CUDA de EmoParse sin modelos."
        )
    )
    parser.add_argument("--profile", choices=sorted(DOCKERFILES), required=True)
    parser.add_argument("--image", default=None, help="Tag local; default emoparse:<profile>.")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Usar una imagen local ya construida y ejecutar solamente los smokes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    image = args.image or DEFAULT_IMAGES[args.profile]
    smoke(args.profile, image, build=not args.no_build)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

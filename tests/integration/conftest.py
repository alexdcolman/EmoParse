# ══════════════════════════════════════════════════════════════════════════════
#  tests.integration.conftest
#
#  Fixtures comunes a tests de integración con backends LLM reales.
#
#  Diseño:
#   - Cada modelo se localiza por convención en `models/` o vía env var.
#   - Si no se encuentra, los tests que lo usan se saltean (NO fallan).
#     Esto hace que `pytest tests/` corra limpio en máquinas sin modelos
#     instalados (CI público), pero ejecute los integration tests cuando
#     el modelo está disponible (tu máquina local).
#
#  Convención de paths:
#
#       <project_root>/
#       ├── pyproject.toml         ← raíz del repo
#       ├── src/emoparse/...
#       ├── tests/...
#       └── models/                ← acá viven los GGUFs
#           └── phi-4-mini-*.gguf
#
#  Override por env var:
#       EMOPARSE_MODELS_DIR=/otra/ruta/models pytest tests/integration
#       EMOPARSE_PHI4_MINI_PATH=/ruta/al/modelo.gguf pytest ...
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
from pathlib import Path

import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  Resolución del directorio de modelos
# ══════════════════════════════════════════════════════════════════════════════

def _project_root() -> Path:
    """Resuelve la raíz del proyecto (donde vive pyproject.toml).

    Estrategia: subir desde `__file__` hasta encontrar pyproject.toml.
    Robusto a movimientos del directorio tests/.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    # Fallback: 2 niveles arriba (tests/integration → tests → root).
    return here.parents[2]


def _models_dir() -> Path:
    """Devuelve el directorio de modelos según convención o env var."""
    override = os.environ.get("EMOPARSE_MODELS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return _project_root() / "models"


# ══════════════════════════════════════════════════════════════════════════════
#  Auto-skip cuando llama-cpp-python no está instalado
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def _llamacpp_available() -> bool:
    """True si llama-cpp-python se puede importar.

    No usamos esto directamente; las fixtures que cargan modelos lo
    chequean y skip si no está. Tener una fixture session-scoped evita
    intentar importar 20 veces.
    """
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Localización de modelos
# ══════════════════════════════════════════════════════════════════════════════

def _find_gguf(patterns: list[str], env_var: str) -> Path | None:
    """Busca un GGUF que matchee cualquiera de los `patterns` (glob).

    Prioridad:
        1. env var (si está y existe).
        2. Búsqueda por glob en models/.
        3. None si no se encuentra.

    `patterns` es lista para tolerar variaciones de nombre. Por ejemplo,
    phi-4-mini puede aparecer como:
        Phi-4-mini-instruct-Q4_K_M.gguf
        phi4mini.IQ4_XS.gguf
        Phi_4_Mini_Q5_K_M.gguf
    Probamos varios patterns insensibles a case y separadores.
    """
    override = os.environ.get(env_var)
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file():
            return p
        return None

    models_dir = _models_dir()
    if not models_dir.is_dir():
        return None

    # Listamos todos los .gguf y matcheamos case-insensitive.
    # No usamos pathlib.glob porque queremos case-insensitive (rglob no
    # lo soporta de forma portable).
    candidates = sorted(models_dir.rglob("*.gguf"))
    if not candidates:
        return None

    def _matches(path: Path, pattern_tokens: list[str]) -> bool:
        """Todos los tokens deben aparecer en el nombre, en orden flexible."""
        name = path.name.lower()
        return all(tok in name for tok in pattern_tokens)

    for pattern in patterns:
        # Pattern viene como string con tokens separados por *. Los partimos.
        tokens = [t for t in pattern.lower().split("*") if t]
        for candidate in candidates:
            if _matches(candidate, tokens):
                return candidate
    return None


@pytest.fixture(scope="session")
def phi4_mini_path() -> Path:
    """Ruta al GGUF de phi-4-mini, o skip si no se encuentra.

    Patterns probados (case-insensitive, glob-style):
        - phi*4*mini
        - phi4*mini
        - phi*mini
    """
    path = _find_gguf(
        patterns=["phi*4*mini", "phi4*mini", "phi*mini"],
        env_var="EMOPARSE_PHI4_MINI_PATH",
    )
    if path is None:
        pytest.skip(
            "phi-4-mini GGUF no encontrado. "
            f"Buscado en {_models_dir()} y EMOPARSE_PHI4_MINI_PATH. "
            "Bajá el modelo o seteá EMOPARSE_PHI4_MINI_PATH para correr este test."
        )
    return path


# ══════════════════════════════════════════════════════════════════════════════
#  Configuración del modelo para tests
#
#  Mantenemos los parámetros conservadores para que el test:
#   - Cargue rápido (n_ctx chico).
#   - Sea determinístico (seed fija, temp=0).
#   - No pida más VRAM de la disponible (n_gpu_layers permisivo).
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def phi4_mini_config(phi4_mini_path: Path) -> dict[str, object]:
    """Config del modelo phi-4-mini para LlamaCppBackend.

    `n_gpu_layers=-1` ofrece todas las capas a GPU; si no hay GPU,
    llama.cpp cae a CPU automáticamente. Si tu setup no tiene CUDA,
    overrride con env var `EMOPARSE_TEST_N_GPU_LAYERS=0`.
    """
    n_gpu_layers = int(os.environ.get("EMOPARSE_TEST_N_GPU_LAYERS", "-1"))
    return {
        "backend": "llama_cpp",
        "path": str(phi4_mini_path),
        "context_length": 4096,  # suficiente para los tests; carga rápido
        "n_gpu_layers": n_gpu_layers,
        "max_tokens": 512,
        "temperature": 0.0,      # determinístico para los asserts
        "seed": 42,
    }

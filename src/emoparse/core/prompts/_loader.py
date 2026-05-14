# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts._loader
#
#  Loader Jinja2 compartido por todos los prompts del proyecto.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template


#: Path al directorio templates/.
_TEMPLATES_DIR: Path = Path(__file__).parent / "templates"


@lru_cache(maxsize=1)
def _env() -> Environment:
    """Construye el Environment Jinja2 una sola vez por proceso."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def get_template(name: str) -> Template:
    """Devuelve un Template compilado para <name>.jinja2."""
    return _env().get_template(f"{name}.jinja2")


def render(name: str, **context: object) -> str:
    """Renderiza un template y devuelve el string resultado."""
    tmpl = get_template(name)
    return tmpl.render(**context)

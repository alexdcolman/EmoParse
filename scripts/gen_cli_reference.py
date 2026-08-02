#!/usr/bin/env python
# ══════════════════════════════════════════════════════════════════════════════
#  scripts/gen_cli_reference.py
#
#  Genera la referencia de comandos recorriendo el parser real del CLI.
#
#  Dos salidas desde una única fuente (el árbol de subparsers):
#  - docs/comandos.md   : referencia completa en markdown.
#  - docs/comandos.html : la misma referencia insertada entre los marcadores
#    de la página del sitio, que conserva a mano el marco (cabecera,
#    navegación, pie) compartido con las demás páginas.
#
#  Con --check no escribe nada y devuelve exit code 1 si algún archivo
#  quedó distinto de lo que produce el parser vigente. Es la verificación
#  que impide que la referencia se desactualice.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

from emoparse.cli.__main__ import build_parser

#: Raíz del repositorio, deducida desde la ubicación de este script.
_RAIZ = Path(__file__).resolve().parent.parent

#: Salidas.
_MD = _RAIZ / "docs" / "comandos.md"
_HTML = _RAIZ / "docs" / "comandos.html"

#: Marcadores dentro de la página del sitio. El contenido entre cada par se
#: reemplaza; todo lo demás queda tal como está escrito a mano.
_MARCAS = {
    "indice": ("<!-- indice:inicio -->", "<!-- indice:fin -->"),
    "cuerpo": ("<!-- comandos:inicio -->", "<!-- comandos:fin -->"),
}


class ReferenceError(Exception):
    """Falla al generar o verificar la referencia."""


# ══════════════════════════════════════════════════════════════════════════════
#  Lectura del parser
# ══════════════════════════════════════════════════════════════════════════════

def _acciones(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    """Acciones documentables de un parser: sin la ayuda ni los subparsers."""
    return [
        a for a in parser._actions
        if not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))
        and a.help != argparse.SUPPRESS
    ]


def _subcomandos(
    parser: argparse.ArgumentParser,
) -> dict[str, argparse.ArgumentParser]:
    """Subcomandos en el orden en que fueron registrados."""
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return dict(a.choices)
    raise ReferenceError("El parser principal no declara subcomandos.")


def _etiqueta(action: argparse.Action) -> str:
    """Cómo se escribe la opción: `--flag, -f` o el nombre si es posicional."""
    if action.option_strings:
        return ", ".join(action.option_strings)
    return str(action.metavar or action.dest)


def _valores(action: argparse.Action) -> str:
    """Qué admite la opción: lista cerrada, marcador, o nada si es un switch."""
    if action.choices:
        return " | ".join(str(c) for c in action.choices)
    if action.nargs == 0 or isinstance(action, argparse._StoreTrueAction):
        return ""
    return str(action.metavar or action.dest).upper()


def _default(action: argparse.Action) -> str:
    """Valor por default, vacío cuando no hay uno informativo."""
    if action.required:
        return "requerido"
    if action.default in (None, False, argparse.SUPPRESS):
        return ""
    return str(action.default)


def _descripcion(parser: argparse.ArgumentParser, ayuda: str) -> str:
    """Texto largo del subcomando; si no tiene, el corto de la lista."""
    return " ".join((parser.description or ayuda or "").split())


def _ayuda_corta(principal: argparse.ArgumentParser, nombre: str) -> str:
    """Ayuda de una línea que el subcomando declara en la lista general."""
    for a in principal._actions:
        if isinstance(a, argparse._SubParsersAction):
            for eleccion in a._choices_actions:
                if eleccion.dest == nombre:
                    return " ".join((eleccion.help or "").split())
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  Markdown
# ══════════════════════════════════════════════════════════════════════════════

def _md_celda(texto: str) -> str:
    """Escapa lo que rompería una celda de tabla markdown."""
    return " ".join(texto.split()).replace("|", "\\|")


def _md_tabla(acciones: list[argparse.Action]) -> list[str]:
    """Tabla de opciones. Vacía si el subcomando no declara ninguna."""
    if not acciones:
        return ["Sin opciones propias.", ""]
    filas = [
        "| Opción | Valor | Default | Qué hace |",
        "|---|---|---|---|",
    ]
    for a in acciones:
        filas.append(
            f"| `{_md_celda(_etiqueta(a))}` | {_md_celda(_valores(a))} "
            f"| {_md_celda(_default(a))} | {_md_celda(a.help or '')} |"
        )
    filas.append("")
    return filas


def render_markdown(parser: argparse.ArgumentParser) -> str:
    """Referencia completa en markdown."""
    lineas = [
        "# Referencia de comandos",
        "",
        "Generado desde el parser del CLI con `scripts/gen_cli_reference.py`.",
        "No editar a mano: los cambios se hacen en el módulo del subcomando.",
        "",
        "## Opciones globales",
        "",
        "Válidas para cualquier subcomando, escritas antes de él.",
        "",
    ]
    lineas += _md_tabla(_acciones(parser))

    for nombre, sub in _subcomandos(parser).items():
        lineas += [
            f"## `emoparse {nombre}`",
            "",
            _descripcion(sub, _ayuda_corta(parser, nombre)),
            "",
        ]
        lineas += _md_tabla(_acciones(sub))
    return "\n".join(lineas).rstrip() + "\n"


# ══════════════════════════════════════════════════════════════════════════════
#  HTML
# ══════════════════════════════════════════════════════════════════════════════

def _h(texto: str) -> str:
    """Texto plano listo para insertar en HTML."""
    return html.escape(" ".join(texto.split()))


def _html_tabla(acciones: list[argparse.Action]) -> list[str]:
    """Tabla de opciones con el marcado de tabla del sitio."""
    if not acciones:
        return ['    <p class="marginal">Sin opciones propias.</p>']
    filas = [
        '    <div class="tabla-caja">',
        "    <table>",
        "      <thead><tr><th>Opción</th><th>Valor</th><th>Default</th>"
        "<th>Qué hace</th></tr></thead>",
        "      <tbody>",
    ]
    for a in acciones:
        valores = _h(_valores(a))
        default = _h(_default(a))
        filas.append(
            f"        <tr><td><code>{_h(_etiqueta(a))}</code></td>"
            f"<td>{f'<code>{valores}</code>' if valores else ''}</td>"
            f"<td>{f'<code>{default}</code>' if default else ''}</td>"
            f"<td>{_h(a.help or '')}</td></tr>"
        )
    filas += ["      </tbody>", "    </table>", "    </div>"]
    return filas


def render_html(parser: argparse.ArgumentParser) -> dict[str, str]:
    """Fragmentos de índice y cuerpo para insertar en la página del sitio."""
    subcomandos = _subcomandos(parser)

    indice = ['      <li><a href="#globales">Opciones globales</a></li>']
    indice += [
        f'      <li><a href="#{nombre}">emoparse {nombre}</a></li>'
        for nombre in subcomandos
    ]

    cuerpo = [
        '    <h2 id="globales">Opciones globales</h2>',
        "",
        "    <p>Válidas para cualquier subcomando, escritas antes de él.</p>",
        "",
    ]
    cuerpo += _html_tabla(_acciones(parser))

    for nombre, sub in subcomandos.items():
        cuerpo += [
            "",
            f'    <h2 id="{nombre}">emoparse {nombre}</h2>',
            "",
            f"    <p>{_h(_descripcion(sub, _ayuda_corta(parser, nombre)))}</p>",
            "",
        ]
        cuerpo += _html_tabla(_acciones(sub))

    return {"indice": "\n".join(indice), "cuerpo": "\n".join(cuerpo)}


def _insertar(pagina: str, fragmentos: dict[str, str]) -> str:
    """Reemplaza lo que hay entre cada par de marcadores de la página."""
    for clave, (inicio, fin) in _MARCAS.items():
        i, f = pagina.find(inicio), pagina.find(fin)
        if i == -1 or f == -1 or f < i:
            raise ReferenceError(
                f"Faltan los marcadores {inicio} / {fin} en {_HTML.name}."
            )
        pagina = (
            pagina[: i + len(inicio)]
            + "\n"
            + fragmentos[clave]
            + "\n"
            + pagina[f:]
        )
    return pagina


# ══════════════════════════════════════════════════════════════════════════════
#  Entrada
# ══════════════════════════════════════════════════════════════════════════════

def _escribir(destino: Path, contenido: str, check: bool) -> bool:
    """Escribe el archivo, o informa si difiere cuando se pidió verificar.

    Devuelve True si el contenido en disco ya coincidía.
    """
    actual = destino.read_text(encoding="utf-8") if destino.is_file() else None
    if actual == contenido:
        return True
    if check:
        print(f"desactualizado: {destino.relative_to(_RAIZ)}", file=sys.stderr)
        return False
    destino.write_text(contenido, encoding="utf-8")
    print(f"escrito: {destino.relative_to(_RAIZ)}")
    return False


def main(argv: list[str] | None = None) -> int:
    """Genera o verifica la referencia. Devuelve exit code (0 = ok)."""
    ap = argparse.ArgumentParser(
        description="Genera la referencia de comandos desde el parser del CLI.",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="No escribe: falla si la referencia en disco quedó desactualizada.",
    )
    args = ap.parse_args(argv)

    parser = build_parser()
    try:
        md = render_markdown(parser)
        if not _HTML.is_file():
            raise ReferenceError(
                f"No existe {_HTML.relative_to(_RAIZ)}: hace falta la página "
                "con el marco del sitio y sus marcadores."
            )
        pagina = _insertar(_HTML.read_text(encoding="utf-8"), render_html(parser))
    except ReferenceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    ok_md = _escribir(_MD, md, args.check)
    ok_html = _escribir(_HTML, pagina, args.check)

    if args.check and not (ok_md and ok_html):
        print(
            "Regenerá con: python scripts/gen_cli_reference.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
